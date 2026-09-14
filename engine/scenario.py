"""scenario.json schema (SPEC Appendix). Pydantic validates shape; `WeiInt`
parses the spec's "<mantissa>e<exponent>" string convention (e.g.
"1000000e18") into an exact Python int — these values are too large to pass
through a float without losing precision.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict
from pydantic.alias_generators import to_camel

_WEI_RE = re.compile(r"(\d+)[eE](\d+)")


def parse_wei(value: int | str) -> int:
    if isinstance(value, int):
        return value
    s = str(value).strip()
    m = _WEI_RE.fullmatch(s)
    if m:
        mantissa, exponent = m.groups()
        return int(mantissa) * (10 ** int(exponent))
    return int(s)


WeiInt = Annotated[int, BeforeValidator(parse_wei)]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AmmConfig(CamelModel):
    reserve_usd: WeiInt
    reserve_col: WeiInt
    fee_bps: int = 0


class LendingConfig(CamelModel):
    usd_liquidity: WeiInt
    collateral_factor_bps: int


class FlashConfig(CamelModel):
    fee_bps: int


class AttackerConfig(CamelModel):
    initial_capital_usd: WeiInt


class EvaluatorConfig(CamelModel):
    reference_price_usd: WeiInt


class GasConfig(CamelModel):
    gas_price_gwei: int
    eth_price_usd: WeiInt


class FitnessWeights(CamelModel):
    price_deviation: float = 1.0
    capacity_per_capital: float = 1.0
    bad_debt: float = 2.0
    profit: float = 2.0
    novelty: float = 0.5


class SearchConfig(CamelModel):
    max_actions: int = 6
    budget_candidates: int = 50_000
    fitness_weights: FitnessWeights = FitnessWeights()
    selection_epsilon: float = 0.1


class Scenario(CamelModel):
    seed: int
    amm: AmmConfig
    lending: LendingConfig
    flash: FlashConfig
    attacker: AttackerConfig
    evaluator: EvaluatorConfig
    gas: GasConfig
    search: SearchConfig

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        return cls.model_validate(json.loads(Path(path).read_text()))
