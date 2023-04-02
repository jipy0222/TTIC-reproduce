"""Different batched non-parametric span representations."""
import torch
import torch.nn as nn
import numpy as np
from utils import get_span_mask
from abc import ABC, abstractmethod
import encoder


class SpanRepr(ABC, nn.Module):
    """Abstract class describing span representation."""

    def __init__(self, input_dim, use_proj=False, proj_dim=256):
        super(SpanRepr, self).__init__()
        self.input_dim = input_dim
        self.proj_dim = proj_dim
        self.use_proj = use_proj
        if use_proj:
            self.proj = nn.Linear(input_dim, proj_dim)

    @abstractmethod
    def forward(self, encoded_input, start_ids, end_ids):
        raise NotImplementedError

    def get_input_dim(self):
        return self.input_dim

    @abstractmethod
    def get_output_dim(self):
        raise NotImplementedError


class MeanSpanRepr(SpanRepr, nn.Module):
    """Class implementing the avg span representation."""

    def forward(self, encoded_input, start_ids, end_ids):
        if self.use_proj:
            encoded_input = self.proj(encoded_input)
        span_lengths = (end_ids - start_ids + 1).unsqueeze(1)
        span_masks = get_span_mask(start_ids, end_ids, encoded_input.shape[1])
        span_repr = torch.sum(encoded_input * span_masks, dim=1) / span_lengths.float()
        return span_repr

    def get_output_dim(self):
        if self.use_proj:
            return self.proj_dim
        else:
            return self.input_dim


class EndPointRepr(SpanRepr, nn.Module):
    """Class implementing the diff span representation - [h_j; h_i]"""

    def forward(self, encoded_input, start_ids, end_ids):
        if self.use_proj:
            encoded_input = self.proj(encoded_input)
        batch_size = encoded_input.shape[0]
        span_repr = torch.cat([encoded_input[torch.arange(batch_size), start_ids, :],
                               encoded_input[torch.arange(batch_size), end_ids, :]], dim=1)
        return span_repr

    def get_output_dim(self):
        if self.use_proj:
            return 2 * self.proj_dim
        else:
            return 2 * self.input_dim


class DiffSumSpanRepr(SpanRepr, nn.Module):
    """Class implementing the diff_sum span representation - [h_j - h_i; h_j + h_i]"""

    def forward(self, encoded_input, start_ids, end_ids):
        if self.use_proj:
            encoded_input = self.proj(encoded_input)
        batch_size = encoded_input.shape[0]
        span_repr = torch.cat([
            encoded_input[torch.arange(batch_size), end_ids, :]
            - encoded_input[torch.arange(batch_size), start_ids, :],
            encoded_input[torch.arange(batch_size), end_ids, :]
            + encoded_input[torch.arange(batch_size), start_ids, :]
            ], dim=1)
        return span_repr

    def get_output_dim(self):
        if self.use_proj:
            return 2 * self.proj_dim
        else:
            return 2 * self.input_dim


class MaxSpanRepr(SpanRepr, nn.Module):
    """Class implementing the max-pool span representation."""

    def forward(self, encoded_input, start_ids, end_ids):
        if self.use_proj:
            encoded_input = self.proj(encoded_input)
        span_masks = get_span_mask(start_ids, end_ids, encoded_input.shape[1])
        # put -inf to irrelevant positions
        tmp_repr = encoded_input * span_masks - 1e10 * (1 - span_masks)
        span_repr = torch.max(tmp_repr, dim=1)[0]
        return span_repr

    def get_output_dim(self):
        if self.use_proj:
            return self.proj_dim
        else:
            return self.input_dim


class AttnSpanRepr(SpanRepr, nn.Module):
    """Class implementing the attention-based span representation."""

    def __init__(self, input_dim, use_proj=False, proj_dim=256):
        """If use_endpoints is true then concatenate the end points to attention-pooled span repr.
        Otherwise just return the attention pooled term.
        """
        super(AttnSpanRepr, self).__init__(input_dim, use_proj=use_proj, proj_dim=proj_dim)
        if use_proj:
            input_dim = proj_dim
        self.attention_params = nn.Linear(input_dim, 1)
        # Initialize weight to zero weight
        # self.attention_params.weight.data.fill_(0)
        # self.attention_params.bias.data.fill_(0)

    def forward(self, encoded_input, start_ids, end_ids):
        if self.use_proj:
            encoded_input = self.proj(encoded_input)

        span_mask = get_span_mask(start_ids, end_ids, encoded_input.shape[1])
        attn_mask = (1 - span_mask) * (-1e10)
        attn_logits = self.attention_params(encoded_input) + attn_mask
        attention_wts = nn.functional.softmax(attn_logits, dim=1)
        attention_term = torch.sum(attention_wts * encoded_input, dim=1)
        return attention_term

    def get_output_dim(self):
        if not self.use_endpoints:
            if self.use_proj:
                return self.proj_dim
            else:
                return self.input_dim
        else:
            if self.use_proj:
                return 3 * self.proj_dim
            else:
                return 3 * self.input_dim


def get_span_module(input_dim, method="avg", use_proj=False, proj_dim=256):
    """Initializes the appropriate span representation class and returns the object.
    """
    if method == "mean":
        return MeanSpanRepr(input_dim, use_proj=use_proj, proj_dim=proj_dim)
    elif method == "max":
        return MaxSpanRepr(input_dim, use_proj=use_proj, proj_dim=proj_dim)
    elif method == "diff_sum":
        return DiffSumSpanRepr(input_dim, use_proj=use_proj, proj_dim=proj_dim)
    elif method == "endpoint":
        return EndPointRepr(input_dim, use_proj=use_proj, proj_dim=proj_dim)
    elif method == "attn":
        return AttnSpanRepr(input_dim, use_proj=use_proj, proj_dim=proj_dim)
    else:
        raise NotImplementedError


if __name__ == '__main__':
    # span_model = AttnSpanRepr(768, use_endpoints=True, use_proj=True)
    # print(span_model.get_output_dim())
    # print(span_model.use_proj)

    mymodel = encoder.Encoder(model='bert', model_size='base', use_proj=False).cuda()
    tokenized_input = mymodel.tokenize_sentence(
        "Hello beautiful world!", get_subword_indices=False)
    output = mymodel(tokenized_input)
    print("output_size:", output.size())
    print("output:", output)

    span_model = get_span_module(768, method='max', use_proj=True).cuda()
    print(span_model.get_output_dim())
    print(span_model.use_proj)
    start = np.array([0])
    end = np.array([3])
    print("start: ", start, "end: ", end)
    span_output = span_model(output, torch.from_numpy(start), torch.from_numpy(end))
    print(span_output)
    print(span_output.size())