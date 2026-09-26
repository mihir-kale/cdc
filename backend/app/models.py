from pydantic import BaseModel


class Lender(BaseModel):
    id: str
    name: str
    states: list[str]
    product: str
    apr_range: str
    complaint_count: int
