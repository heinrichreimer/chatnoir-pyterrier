from os import environ

from pytest import fixture, skip

from chatnoir_api import Index

from chatnoir_pyterrier.retrieve import Feature


@fixture(
    scope="module",
    params=[True, False]
)
def staging(request) -> str:
    return request.param


@fixture(scope="module")
def api_key(staging: bool) -> str:
    key: str
    if staging:
        key = "CHATNOIR_API_KEY_STAGING"
    else:
        key = "CHATNOIR_API_KEY"
    if key not in environ:
        raise RuntimeError(
            f"Must specify ChatNoir api key "
            f"in the {key} environment variable "
            f"to run this test."
        )
    return environ[key]


@fixture(scope="module", params=["python library", "search engine"])
def query(request) -> str:
    return request.param


@fixture(
    scope="module",
    params=[
        Index.ClueWeb09,
        Index.ClueWeb12,
        Index.ClueWeb22,
        Index.CommonCrawl1511,
        Index.CommonCrawl1704,
    ]
)
def index(request, staging: bool) -> Index:
    if not staging and request.param == Index.ClueWeb22:
        skip("ClueWeb22 is not available on the production API.")
    if staging and request.param == Index.CommonCrawl1511:
        skip("Common Crawl 15/11 is not available on the staging API.")
    if staging and request.param == Index.CommonCrawl1704:
        skip("Common Crawl 17/04 is not available on the staging API.")
    return request.param


@fixture(scope="module", params=[feature for feature in Feature])
def feature(request) -> Feature:
    return request.param
