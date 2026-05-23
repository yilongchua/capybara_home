"""Configuration for external benchmark calibration."""

from pydantic import BaseModel, Field


class BenchmarksConfig(BaseModel):
    """Benchmark suite configuration."""

    enabled: bool = Field(default=False, description="Enable benchmark suite execution helpers.")
    suite: str = Field(default="coding", description="Default benchmark suite name.")
    report_dir: str = Field(default=".capyhome/benchmarks", description="Directory for benchmark reports.")
    fail_on_regression: bool = Field(default=False, description="Whether benchmark regression should fail gates.")
    regression_threshold: float = Field(default=0.02, ge=0.0, le=1.0, description="Allowed score regression before marking failure.")


_benchmarks_config: BenchmarksConfig = BenchmarksConfig()


def get_benchmarks_config() -> BenchmarksConfig:
    """Get current benchmark configuration."""
    return _benchmarks_config


def set_benchmarks_config(config: BenchmarksConfig) -> None:
    """Set benchmark configuration."""
    global _benchmarks_config
    _benchmarks_config = config


def load_benchmarks_config_from_dict(config_dict: dict) -> None:
    """Load benchmark configuration from dictionary."""
    global _benchmarks_config
    _benchmarks_config = BenchmarksConfig(**config_dict)
