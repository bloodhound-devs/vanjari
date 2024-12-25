import torch
from torch import nn
from hierarchicalsoftmax import HierarchicalSoftmaxLazyLinear, SoftmaxNode


class VanjariAttentionModel(nn.Module):
    def __init__(
        self, 
        classification_tree:SoftmaxNode, 
        features:int=5120, 
        intermediate_layers:int=0, 
        growth_factor:float=2.0, 
        dropout:float=0.0,
        attention_hidden_size:int=512,
    ):
        super().__init__()

        assert growth_factor > 0.0
        
        self.classification_tree = classification_tree
        modules = [nn.LazyLinear(out_features=features), nn.PReLU()]
        for _ in range(intermediate_layers):
            out_features = int(features * growth_factor + 0.5)
            modules += [nn.LazyLinear(out_features=out_features), nn.PReLU(), nn.Dropout(dropout)]
            features = out_features

        self.sequential = nn.Sequential(*modules)

        self.attention_layer = nn.Sequential(
            nn.Linear(out_features, attention_hidden_size),  # (batch_size, seq_length, hidden_size)
            nn.Tanh(),
            nn.Linear(attention_hidden_size, 1)  # (batch_size, seq_length, 1)
        )

        self.classifier = HierarchicalSoftmaxLazyLinear(root=classification_tree)
        self.model_dtype = next(self.sequential.parameters()).dtype

    def forward(self, x):        
        if self.model_dtype != x.dtype:
            x = x.to(dtype=self.model_dtype)

        x = self.sequential(x)

        attention_scores = self.attention_layer(x)
        attention_weights = torch.softmax(attention_scores, dim=1)

        context_vector = torch.sum(attention_weights * x, dim=1)

        result = self.classifier(context_vector)

        return result
        
