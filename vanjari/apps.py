import random
import torchapp as ta
from corgi.apps import Corgi
from corgi.seqtree import SeqTree
from torchapp.download import cached_download
from pathlib import Path
import pandas as pd
from seqbank import SeqBank
from rich.progress import track
from hierarchicalsoftmax.metrics import RankAccuracyTorchMetric, GreedyAccuracy
from hierarchicalsoftmax.metrics import greedy_accuracy
from torchmetrics import Metric
import pyfastx


from hierarchicalsoftmax import SoftmaxNode

from .nucleotidetransformer import NucleotideTransformerEmbedding 

class Vanjari(Corgi):
    @ta.method    
    def metrics(self) -> list[tuple[str,Metric]]:
        rank_accuracy = RankAccuracyTorchMetric(
            root=self.classification_tree, 
            ranks={1+i:f"rank_{i}" for i in range(9)},
        )
        return [('species_accuracy', GreedyAccuracy(root=self.classification_tree, name="species_accuracy")), ('rank_accuracy', rank_accuracy)]

    @ta.method
    def monitor(self) -> str:
        return "species_accuracy"

    @ta.tool
    def max_depth(
        self, 
        seqtree:Path=ta.Param(..., help="Path to the SeqTree"), 
    ):
        seqtree = SeqTree.load(Path(seqtree))
        max_depth = 0
        for leaf in track(seqtree.classification_tree.leaves):
            max_depth = max(max_depth, len(leaf.ancestors))
        print(f"Max depth: {max_depth}")

    def taxonomy_df(self, max_accessions:int=0):
        url = "https://ictv.global/sites/default/files/VMR/VMR_MSL39.v4_20241106.xlsx"
        local_path = self.cache_dir() / "VMR_MSL39.v4_20241106.xlsx"
        cached_download(url, local_path)
        df = pd.read_excel(local_path, sheet_name="VMR MSL39")
        df = df.fillna('')
        if max_accessions:
            df = df.head(max_accessions)
        return df

    @ta.tool
    def preprocess(
        self, 
        seqtree:Path=ta.Param(..., help="Path to save the SeqTree"), 
        seqbank:Path=ta.Param(..., help="Path to save the SeqBank"),
        max_accessions:int=ta.Param(0, help="Maximum number of accessions to add"),
        fasta_dir:Path=ta.Param(..., help="Path to the FASTA directory"),
    ):
        seqtree_path = Path(seqtree)
        seqbank_path = Path(seqbank)
        fasta_dir = Path(fasta_dir)

        # Build the SeqBank
        seqbank_path.parent.mkdir(parents=True, exist_ok=True)
        seqbank = SeqBank(path=seqbank_path, write=True)

        df = self.taxonomy_df(max_accessions)
        taxonomic_columns = [
            'Realm', 'Subrealm',
            'Kingdom', 'Subkingdom', 'Phylum', 'Subphylum', 'Class', 'Subclass',
            'Order', 'Suborder', 'Family', 'Subfamily', 'Genus', 'Subgenus',
            'Species',
        ]
        root = SoftmaxNode(name="Virus", rank="Root")
        seqtree = SeqTree(root)
        
        print("Building classification tree")
        for _, row in track(df.iterrows(), total=len(df)):
            current_node = root
            genbank_accession = row['Virus GENBANK accession'].strip()
            if not genbank_accession:
                continue

            for rank in taxonomic_columns:
                value = row[rank]
                if not value:
                    continue

                found = False
                for child in current_node.children:
                    if child.name == value:
                        found = True
                        break
                current_node = child if found else SoftmaxNode(name=value, parent=current_node, rank=rank) 

            
            accessions = genbank_accession.split(";")
            for accession in accessions:
                accession = accession.strip()
                if ":" in accession:
                    accession = accession.split(":")[1].strip()
                accession = accession.split(" ")[0]

                # Add the sequence to the SeqBank
                fasta = fasta_dir / f"{accession}.fasta.gz"
                assert fasta.exists(), f"FASTA file not found: {fasta}"
                try:
                    seqbank.add_sequence_from_file(accession, fasta)
                except RuntimeError as e:
                    print(f"Error adding {accession}: {e}")
                    continue

                # Add the sequence to the SeqTree
                partition = random.randint(0, 4)       
                seqtree.add(accession, current_node, partition)

        root.render(filepath="viruses.dot")
        with open("tree.txt", "w") as f:
            f.write(str(root.render()))

        # Save the SeqTree
        seqtree_path.parent.mkdir(parents=True, exist_ok=True)
        seqtree.save(seqtree_path)


class VanjariNT(Vanjari):
    @ta.tool
    def preprocess(
        self, 
        seqtree:Path=ta.Param(..., help="Path to save the SeqTree"), 
        output_dir:Path=ta.Option(default=..., help="A directory to store the output which includes the memmap array, the listing of accessions and an error log."),
        max_accessions:int=ta.Param(0, help="Maximum number of accessions to add"),
        fasta_dir:Path=ta.Param(..., help="Path to the FASTA directory"),
    ):
        seqtree_path = Path(seqtree)
        fasta_dir = Path(fasta_dir)

        model = NucleotideTransformerEmbedding()

        df = self.taxonomy_df(max_accessions)
        taxonomic_columns = [
            'Realm', 'Subrealm',
            'Kingdom', 'Subkingdom', 'Phylum', 'Subphylum', 'Class', 'Subclass',
            'Order', 'Suborder', 'Family', 'Subfamily', 'Genus', 'Subgenus',
            'Species',
        ]
        root = SoftmaxNode(name="Virus", rank="Root")
        seqtree = SeqTree(root)
        
        print("Building classification tree")
        for _, row in track(df.iterrows(), total=len(df)):
            current_node = root
            genbank_accession = row['Virus GENBANK accession'].strip()
            if not genbank_accession:
                continue

            for rank in taxonomic_columns:
                value = row[rank]
                if not value:
                    continue

                found = False
                for child in current_node.children:
                    if child.name == value:
                        found = True
                        break
                current_node = child if found else SoftmaxNode(name=value, parent=current_node, rank=rank) 

            accessions = genbank_accession.split(";")
            for accession in accessions:
                accession = accession.strip()
                if ":" in accession:
                    accession = accession.split(":")[1].strip()
                accession = accession.split(" ")[0]

                # Add the sequence to the SeqBank
                fasta = fasta_dir / f"{accession}.fasta.gz"
                assert fasta.exists(), f"FASTA file not found: {fasta}"

                # Read the sequence
                for i, seq in pyfastx.Fasta(str(fasta), build_index=False):
                    assert i == 0, "More than one sequence found"
                    embedding = model.embed(seq)
                    breakpoint()

                # Add the sequence to the SeqTree
                partition = random.randint(0, 4)       
                seqtree.add(accession, current_node, partition)

        root.render(filepath="viruses.dot")
        with open("tree.txt", "w") as f:
            f.write(str(root.render()))

        # Save the SeqTree
        seqtree_path.parent.mkdir(parents=True, exist_ok=True)
        seqtree.save(seqtree_path)
