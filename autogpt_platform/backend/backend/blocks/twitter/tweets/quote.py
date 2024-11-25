from typing import cast

import tweepy
from tweepy.client import Response

from backend.blocks.twitter._auth import (
    TEST_CREDENTIALS,
    TEST_CREDENTIALS_INPUT,
    TwitterCredentials,
    TwitterCredentialsField,
    TwitterCredentialsInput,
)
from backend.blocks.twitter._builders import TweetExpansionsBuilder
from backend.blocks.twitter._serializer import (
    IncludesSerializer,
    ResponseDataSerializer,
)
from backend.blocks.twitter._types import (
    TweetExcludes,
    TweetExpansionInputs,
    TweetExpansions,
    TweetFields,
    TweetMediaFields,
    TweetPlaceFields,
    TweetPollFields,
    TweetUserFields,
)
from backend.blocks.twitter.tweepy_exceptions import handle_tweepy_exception
from backend.data.block import Block, BlockCategory, BlockOutput, BlockSchema
from backend.data.model import SchemaField


class TwitterGetQuoteTweetsBlock(Block):
    """
    Gets quote tweets for a specified tweet ID
    """

    class Input(TweetExpansionInputs):
        credentials: TwitterCredentialsInput = TwitterCredentialsField(
            ["tweet.read", "users.read", "offline.access"]
        )

        tweet_id: str = SchemaField(
            description="ID of the tweet to get quotes for",
            placeholder="Enter tweet ID",
        )

        max_results: int = SchemaField(
            description="Number of results to return (max 100)",
            default=10,
            required=False,
            advanced=True,
        )

        exclude: list[TweetExcludes] = SchemaField(
            description="Types of tweets to exclude",
            required=False,
            advanced=True,
            is_multi_select=True,
            default=[],
        )

        pagination_token: str = SchemaField(
            description="Token for pagination",
            required=False,
            advanced=True,
            default="",
        )

    class Output(BlockSchema):
        # Common Outputs that user commonly uses
        ids: list = SchemaField(description="All Tweet IDs ")
        texts: list = SchemaField(description="All Tweet texts")
        next_token: str = SchemaField(description="Next token for pagination")

        # Complete Outputs for advanced use
        data: list[dict] = SchemaField(description="Complete Tweet data")
        included: dict = SchemaField(
            description="Additional data that you have requested (Optional) via Expansions field"
        )
        meta: dict = SchemaField(
            description="Provides metadata such as pagination info (next_token) or result counts"
        )

        # error
        error: str = SchemaField(description="Error message if the request failed")

    def __init__(self):
        super().__init__(
            id="9fbdd208-a630-11ef-9b97-ab7a3a695ca3",
            description="This block gets quote tweets for a specific tweet.",
            categories={BlockCategory.SOCIAL},
            input_schema=TwitterGetQuoteTweetsBlock.Input,
            output_schema=TwitterGetQuoteTweetsBlock.Output,
            test_input={
                "tweet_id": "1234567890",
                "max_results": 10,
                "exclude": [],
                "pagination_token": "",
                "credentials": TEST_CREDENTIALS_INPUT,
                "expansions": [],
                "media_fields": [],
                "place_fields": [],
                "poll_fields": [],
                "tweet_fields": [],
                "user_fields": [],
            },
            test_credentials=TEST_CREDENTIALS,
            test_output=[
                ("ids", ["12345", "67890"]),
                ("texts", ["Tweet 1", "Tweet 2"]),
                (
                    "data",
                    [
                        {"id": "12345", "text": "Tweet 1"},
                        {"id": "67890", "text": "Tweet 2"},
                    ],
                ),
                ("included", {}),
                ("meta", {"result_count": 2, "next_token": "next_token_value"}),
                ("next_token", "next_token_value"),
            ],
            test_mock={
                "get_quote_tweets": lambda *args, **kwargs: (
                    ["12345", "67890"],
                    ["Tweet 1", "Tweet 2"],
                    [
                        {"id": "12345", "text": "Tweet 1"},
                        {"id": "67890", "text": "Tweet 2"},
                    ],
                    {},
                    {"result_count": 2, "next_token": "next_token_value"},
                    "next_token_value",
                )
            },
        )

    @staticmethod
    def get_quote_tweets(
        credentials: TwitterCredentials,
        tweet_id: str,
        max_results: int,
        exclude: list[TweetExcludes],
        pagination_token: str,
        expansions: list[TweetExpansions],
        media_fields: list[TweetMediaFields],
        place_fields: list[TweetPlaceFields],
        poll_fields: list[TweetPollFields],
        tweet_fields: list[TweetFields],
        user_fields: list[TweetUserFields],
    ):
        try:
            client = tweepy.Client(
                bearer_token=credentials.access_token.get_secret_value()
            )

            params = {
                "id": tweet_id,
                "max_results": max_results,
                "pagination_token": (
                    None if pagination_token == "" else pagination_token
                ),
                "exclude": None if exclude == [] else exclude,
                "user_auth": False,
            }

            params = (
                TweetExpansionsBuilder(params)
                .add_expansions(expansions)
                .add_media_fields(media_fields)
                .add_place_fields(place_fields)
                .add_poll_fields(poll_fields)
                .add_tweet_fields(tweet_fields)
                .add_user_fields(user_fields)
                .build()
            )

            response = cast(Response, client.get_quote_tweets(**params))

            meta = {}
            tweet_ids = []
            tweet_texts = []
            next_token = None

            if response.meta:
                meta = response.meta
                next_token = meta.get("next_token")

            included = IncludesSerializer.serialize(response.includes)
            data = ResponseDataSerializer.serialize_list(response.data)

            if response.data:
                tweet_ids = [str(tweet.id) for tweet in response.data]
                tweet_texts = [tweet.text for tweet in response.data]

                return tweet_ids, tweet_texts, data, included, meta, next_token

            raise Exception("No quote tweets found")

        except tweepy.TweepyException:
            raise

    def run(
        self,
        input_data: Input,
        *,
        credentials: TwitterCredentials,
        **kwargs,
    ) -> BlockOutput:
        try:
            ids, texts, data, included, meta, next_token = self.get_quote_tweets(
                credentials,
                input_data.tweet_id,
                input_data.max_results,
                input_data.exclude,
                input_data.pagination_token,
                input_data.expansions,
                input_data.media_fields,
                input_data.place_fields,
                input_data.poll_fields,
                input_data.tweet_fields,
                input_data.user_fields,
            )
            if ids:
                yield "ids", ids
            if texts:
                yield "texts", texts
            if next_token:
                yield "next_token", next_token
            if data:
                yield "data", data
            if included:
                yield "included", included
            if meta:
                yield "meta", meta

        except Exception as e:
            yield "error", handle_tweepy_exception(e)
