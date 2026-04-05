"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
BaseScenario — базовый класс для всех сценариев лаборатории.

Порядок вызова в lab_runner:
  1. pick_symbol()                    → symbol | None
  2. get_context(symbol)              → dict | None
  3. generate_signal(symbol, context) → dict | None
  4. apply_risk(signal, cfg)          → dict | None
  5. get_close_event(pos, price)      → (price, reason) | None
"""
import sys
sys.path.insert(0, '/root/apex-system')


class BaseScenario:
    name: str = "BASE"
    description: str = "Base scenario — not for direct use"
    smc_mode: str = "SKIP"

    def pick_symbol(self) -> str | None:
        raise NotImplementedError(f"{self.name}: pick_symbol() not implemented")

    def get_context(self, symbol: str) -> dict | None:
        sys.path.insert(0, '/root/apex-system/strategies/APEX_SCENARIO_LAB')
        from smc.smc_stage import get_context as _get
        return _get(symbol, self.smc_mode)

    def generate_signal(self, symbol: str, context: dict) -> dict | None:
        raise NotImplementedError(f"{self.name}: generate_signal() not implemented")

    def apply_risk(self, signal: dict, lab_config: dict) -> dict | None:
        raise NotImplementedError(f"{self.name}: apply_risk() not implemented")

    def get_close_event(self, position: dict, current_price: float) -> tuple | None:
        raise NotImplementedError(f"{self.name}: get_close_event() not implemented")

    def validate(self) -> bool:
        if not self.name or self.name == "BASE":
            return False
        if self.smc_mode not in ("SKIP", "REQUIRED_SOFT", "REQUIRED_STRICT"):
            return False
        return True

    def __repr__(self):
        return f"<Scenario name={self.name} smc_mode={self.smc_mode}>"
