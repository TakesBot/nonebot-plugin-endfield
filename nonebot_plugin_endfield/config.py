from typing import Optional
from pydantic import BaseModel


class Config(BaseModel):
    endfield_api_key: Optional[str] = None
    endfield_api_baseurl: str = "https://end-api.shallow.ink/"
