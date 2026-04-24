from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterable

from sync.autoapply.models import Listing


class ListingSource(ABC):
    """A source of current job listings.

    Subclasses implement listings() to yield Listing objects. Sources should
    be deterministic for a given snapshot of remote data and safe to call
    repeatedly within one run.
    """

    @abstractmethod
    def listings(self) -> Iterable[Listing]:
        ...
