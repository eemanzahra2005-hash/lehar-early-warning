"""The flood lead-time network (LEHAR Phase 2.5). ** imports torch **

A deliberately small 2-layer GRU: ~44k parameters, which is about 170 KB of
float32 weights. Size is a design constraint here, not an accident — the
exported ONNX has to load inside the same 512 MB box that already holds
scikit-learn, SHAP and matplotlib (CLAUDE.md rule 11), and a student
research project with ~1 million training windows has no business reaching
for a model that could memorise them.

Shape of the thing:

    window      (B, 14, 5)   14 days x [log discharge, rain, tmax, doy sin/cos]
    district_id (B,)         which district this window is from

    embedding   (B, 16)      a learned vector per district, broadcast across
                             all 14 days and concatenated onto every step
    GRU         2 layers, hidden 64, batch_first
    head        Linear(64 -> 3)

    prediction  (B, 3)       normalised log discharge at D+1, D+2, D+3

Why the district embedding rather than one model per district: 107 separate
models would each see ~10,000 windows, and the districts that matter most
(the Indus mainstem ones) behave similarly enough that they should be
learning from each other. The embedding lets one shared recurrent core learn
"how a river rises" while still giving each district somewhere to put its own
character (flashy hill torrent vs. slow canal-fed plain reach).

The GRU reads the whole 14-day window and only the FINAL hidden state feeds
the head — the head's job is "given everything you have seen up to today,
where will this river be in 1, 2 and 3 days", which is exactly one vector.
"""

import torch
from torch import nn

from ml.flood_dl.features import HORIZONS, N_FEATURES, WINDOW_DAYS

DEFAULT_EMBEDDING_DIM = 16
DEFAULT_HIDDEN_SIZE = 64
DEFAULT_NUM_LAYERS = 2


class FloodLeadTimeGRU(nn.Module):
    """Per-district 1-3 day river-discharge forecaster."""

    def __init__(
        self,
        n_districts: int,
        n_features: int = N_FEATURES,
        n_horizons: int = len(HORIZONS),
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        hidden_size: int = DEFAULT_HIDDEN_SIZE,
        num_layers: int = DEFAULT_NUM_LAYERS,
    ):
        super().__init__()
        self.n_districts = n_districts
        self.n_features = n_features
        self.n_horizons = n_horizons
        self.window_days = WINDOW_DAYS

        self.embedding = nn.Embedding(n_districts, embedding_dim)
        self.gru = nn.GRU(
            input_size=n_features + embedding_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.head = nn.Linear(hidden_size, n_horizons)

    def forward(self, window: torch.Tensor, district_id: torch.Tensor) -> torch.Tensor:
        """window: (B, WINDOW_DAYS, n_features); district_id: (B,) int64."""
        # One embedding vector per sample, repeated across the time axis so
        # every step of the sequence knows which river it is looking at.
        embedded = self.embedding(district_id).unsqueeze(1).expand(-1, window.shape[1], -1)
        sequence = torch.cat([window, embedded], dim=-1)
        output, _ = self.gru(sequence)
        return self.head(output[:, -1, :])

    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters())
