from dataclasses import dataclass, field
from enum import unique, auto, Flag
from functools import reduce
from itertools import islice
from typing import Set, Optional, Iterable, Union, Any, Dict, Final

from chatnoir_api import Index
from chatnoir_api.model import Slop
from chatnoir_api.model.result import SearchResult, PhraseSearchResult
from chatnoir_api.v1 import (
    search, search_phrases, DEFAULT_INDEX, DEFAULT_RETRIES,
    DEFAULT_BACKOFF_SECONDS, DEFAULT_SLOP
)
from pandas import DataFrame
from pandas.core.groupby import DataFrameGroupBy
from pyterrier.batchretrieve import BatchRetrieveBase
from pyterrier.model import add_ranks
from tqdm import tqdm


@unique
class Feature(Flag):
    NONE = 0
    UUID = auto()
    INDEX = auto()
    TARGET_HOSTNAME = auto()
    TARGET_URI = auto()
    TARGET = TARGET_HOSTNAME | TARGET_URI
    PAGE_RANK = auto()
    SPAM_RANK = auto()
    RANKS = PAGE_RANK | SPAM_RANK
    TITLE_HIGHLIGHTED = auto()
    TITLE_TEXT = auto()
    TITLE = TITLE_HIGHLIGHTED | TITLE_TEXT
    SNIPPET_HIGHLIGHTED = auto()
    SNIPPET_TEXT = auto()
    SNIPPET = SNIPPET_HIGHLIGHTED | SNIPPET_TEXT
    EXPLANATION = auto()
    HTML = auto()
    HTML_PLAIN = auto()
    ALL = (
            UUID | INDEX | TARGET | RANKS | TITLE | SNIPPET | EXPLANATION |
            HTML | HTML_PLAIN
    )


@dataclass
class ChatNoirRetrieve(BatchRetrieveBase):
    name = "ChatNoirRetrieve"

    api_key: str
    index: Union[Index, Set[Index]] = field(
        default_factory=lambda: DEFAULT_INDEX,
    )
    phrases: bool = False
    slop: Slop = DEFAULT_SLOP
    features: Union[Feature, Set[Feature]] = Feature.NONE
    filter_unknown: bool = False
    num_results: Optional[int] = 10
    page_size: int = 100
    retries: int = DEFAULT_RETRIES
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    verbose: bool = False

    def __post_init__(self):
        super().__init__(verbose=self.verbose)

    def _merge_result(
            self,
            row: Dict[str, Any],
            result: Union[SearchResult, PhraseSearchResult]
    ) -> Dict[str, Any]:
        row = {
            **row,
            "docno": result.trec_id,
            "score": result.score,
        }
        if Feature.UUID in self.features:
            row["uuid"] = result.uuid
        if Feature.INDEX in self.features:
            row["index"] = result.index.value
        if Feature.TARGET_HOSTNAME in self.features:
            row["target_hostname"] = result.target_hostname
        if Feature.TARGET_URI in self.features:
            row["target_uri"] = result.target_uri
        if Feature.PAGE_RANK in self.features:
            row["page_rank"] = result.page_rank
        if Feature.SPAM_RANK in self.features:
            row["spam_rank"] = result.spam_rank
        if Feature.TITLE_HIGHLIGHTED in self.features:
            row["title_highlighted"] = result.title.html
        if Feature.TITLE_TEXT in self.features:
            row["title_text"] = result.title.text
        if Feature.SNIPPET_HIGHLIGHTED in self.features:
            row["snippet_highlighted"] = result.snippet.html
        if Feature.SNIPPET_TEXT in self.features:
            row["snippet_text"] = result.snippet.text
        if Feature.EXPLANATION in self.features:
            row["explanation"] = result.explanation
        if Feature.HTML in self.features:
            row["html"] = result.html_contents(plain=False)
        if Feature.HTML_PLAIN in self.features:
            row["html_plain"] = result.html_contents(plain=True)
        return row

    def _transform_query(self, topic: DataFrame) -> DataFrame:
        if len(topic.index) != 1:
            raise RuntimeError("Can only transform one query at a time.")

        row: Dict[str, Any] = topic.to_dict(orient="records")[0]
        query: str = row["query"]

        page_size: int
        if self.num_results is not None:
            page_size = min(self.page_size, self.num_results)
        else:
            page_size = self.page_size

        features: Feature
        if isinstance(self.features, Set):
            features = reduce(
                lambda feature_a, feature_b: feature_a | feature_b,
                self.features
            )
        else:
            features = self.features

        explain: bool = Feature.EXPLANATION in features

        results: Iterable[Union[SearchResult, PhraseSearchResult]]
        if not self.phrases:
            results = search(
                api_key=self.api_key,
                query=query,
                index=self.index,
                explain=explain,
                page_size=page_size,
            )
        else:
            results = search_phrases(
                api_key=self.api_key,
                query=query,
                index=self.index,
                slop=self.slop,
                explain=explain,
                page_size=page_size,
            )

        if self.filter_unknown:
            # Filter unknown results, i.e., when the TREC ID is missing.
            results = (
                result
                for result in results
                if result.trec_id is not None
            )
            pass

        if self.num_results is not None:
            results = islice(results, self.num_results)

        return DataFrame([
            self._merge_result(row, result)
            for result in results
        ])

    def transform(self, topics: DataFrame) -> DataFrame:

        if not isinstance(topics, DataFrame):
            raise RuntimeError("Can only transform dataframes.")

        if not {'qid', 'query'}.issubset(topics.columns):
            raise RuntimeError("Needs qid and query columns.")

        if len(topics) == 0:
            return self._transform_query(topics)

        topics_by_query: DataFrameGroupBy = topics.groupby(
            by=["qid"],
            as_index=False,
            sort=False,
        )
        if self.verbose:
            # Show progress during reranking queries.
            tqdm.pandas(
                desc="Searching with ChatNoir",
                unit="query",
            )
            topics_by_query = topics_by_query.progress_apply(
                self._transform_query
            )
        else:
            topics_by_query = topics_by_query.apply(self._transform_query)

        retrieved: DataFrame = topics_by_query.reset_index(drop=True)
        retrieved.sort_values(by=["score"], ascending=False)
        retrieved = add_ranks(retrieved)

        return retrieved

    def __hash__(self):
        return hash((
            self.api_key,
            (
                tuple(sorted(self.index, key=lambda index: index.name))
                if isinstance(self.index, Set)
                else self.index
            ),
            self.phrases,
            self.slop,
            (
                list(sorted(self.features))
                if isinstance(self.features, Set)
                else self.features
            ),
            self.filter_unknown,
            self.num_results,
            self.page_size,
            self.retries,
            self.backoff_seconds,
            self.verbose,
        ))
