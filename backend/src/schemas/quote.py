from pydantic import BaseModel, Field


class PriceInput(BaseModel):
    value: int = Field(ge=0, le=1000000000)


class SwapInput(BaseModel):
    # 客户端生成并在中断恢复后复用；服务端据此幂等去重，落盘后重试不会重复换列。
    request_id: str = Field(min_length=8, max_length=120)
    label: str | None = Field(default=None, max_length=80)


class CursorInput(BaseModel):
    page_size: int = Field(ge=1, le=50, default=5)


class FailoverInput(BaseModel):
    scenario_id: int | None = Field(default=None, gt=0)
