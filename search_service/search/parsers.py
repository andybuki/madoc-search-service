import codecs
import json
from functools import reduce
from operator import or_, and_
import pytz
from dateutil import parser
import logging
import unicodedata


# Django imports
from django.conf import settings
from django.contrib.postgres.search import SearchQuery
from django.db.models import Q
from django.utils.translation import get_language


# DRF Imports
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser

from .prezi_upgrader import Upgrader

from .madoc_jwt import (
    request_madoc_site_urn,
)

default_lang = get_language()
upgrader = Upgrader(flags={"default_lang": default_lang})

logger = logging.getLogger(__name__)

# Globals
global_facet_on_manifests = settings.FACET_ON_MANIFESTS_ONLY
global_facet_types = ["metadata"]
global_non_latin_fulltext = settings.NONLATIN_FULLTEXT
global_search_multiple_fields = settings.SEARCH_MULTIPLE_FIELDS


def date_query_value(q_key, value):
    """
    To aid in the faceting, if you get a query type that is date, return a datetime parsed using dateutil,
    otherwise, just return the thing that came in
    """
    if "date" in q_key:
        try:
            parsed_date = parser.parse(value)
            if parsed_date.tzinfo is None or parsed_date.tzinfo.utcoffset(parsed_date) is None:
                query_date = parsed_date.replace(tzinfo=pytz.utc)
            else:
                query_date = parsed_date
        except ValueError:
            query_date = None
        if query_date:
            return query_date
        else:
            return value
    return value


def date_q(value, date_query_type=None):
    date_types = {
        "start": ["indexables__indexable_date_range_end__gte"],
        "end": ["indexables__indexable_date_range_start__lte"],
        "exact": [
            "indexables__indexable_date_range_start",
            "indexables__indexable_date_range_end",
        ],
    }
    if value and date_query_type and date_query_type in date_types.keys():
        try:
            parsed_date = parser.parse(value)
            if parsed_date.tzinfo is None or parsed_date.tzinfo.utcoffset(parsed_date) is None:
                query_date = parsed_date.replace(tzinfo=pytz.utc)
            else:
                query_date = parsed_date
        except ValueError:
            query_date = None
        if query_date:
            return {x: query_date for x in date_types[date_query_type]}
    return


def facet_operator(q_key, field_lookup):
    """
    sorted_facet_query.get('field_lookup', 'iexact')
    """
    if q_key in ["type", "subtype"]:
        return "iexact"
    elif q_key in ["value"]:
        if field_lookup in [
            "exact",
            "iexact",
            "icontains",
            "contains",
            "in",
            "startswith",
            "istartswith",
            "endswith",
            "iendswith",
        ]:
            return field_lookup
        else:
            return "iexact"
    elif q_key in ["indexable_int", "indexable_float"]:
        if field_lookup in ["exact", "gt", "gte", "lt", "lte"]:
            return field_lookup
        else:
            return "exact"
    elif q_key in ["indexable_date_range_start", "indexable_date_range_year"]:
        if field_lookup in ["day", "month", "year", "iso_year", "gt", "gte", "lt", "lte", "exact"]:
            return field_lookup
        else:
            return "exact"
    else:
        return "iexact"


def parse_facets(facet_queries):
    """
    Parse the facet component of a search request into a set of reduced Q filters.
    """
    if facet_queries:
        postfilter_q = []
        # Generate a list of keys concatenated from type and subtype
        # These should be "OR"d together later.
        # e.g.
        # {"metadata|author": []}
        sorted_facets = {
            "|".join([f.get("type", ""), f.get("subtype", "")]): [] for f in facet_queries
        }
        # Copy the query into that lookup so we can get queries against the same
        # type/subtype
        # e.g.
        # {"metadata|author": ["John Smith", "Mary Jones"]}
        for f in facet_queries:
            sorted_facets["|".join([f.get("type", ""), f.get("subtype", "")])].append(f)
        for sorted_facet_key, sorted_facet_queries in sorted_facets.items():
            # For each combination of type/subtype
            # 1. Concatenate all of the queries into an AND
            # e.g. "type" = "metadata" AND "subtype" = "author" AND
            # "indexables" = "John Smith"
            # 2. Concatenate all of thes einto an OR
            # so that you get something with the intent of AUTHOR = (A or B)
            postfilter_q.append(
                reduce(  # All of the queries with the same field are OR'd together
                    or_,
                    [
                        reduce(  # All of the fields within a single facet query are
                            # AND'd together
                            and_,
                            (
                                Q(  # Iterate the keys in the facet dict to generate the Q()
                                    **{
                                        f"indexables__"
                                        f"{(lambda k: 'indexable' if k == 'value' else k)(k)}__"
                                        f"{facet_operator(k, sorted_facet_query.get('field_lookup', 'iexact'))}": date_query_value(
                                            q_key=k, value=v
                                        )
                                    }  # You can pass in something other than iexact
                                    # using the field_lookup key
                                )
                                for k, v in sorted_facet_query.items()
                                if k
                                in [
                                    "type",
                                    "subtype",
                                    "indexable",
                                    "value",
                                    "indexable_int",
                                    "ndexable_float",
                                    "indexable_date_range_start",
                                    "indexable_date_range_end",
                                ]  # These are the fields to query
                            ),
                        )
                        for sorted_facet_query in sorted_facet_queries
                    ],
                )
            )
        return postfilter_q
    return


def is_latin(text):
    """
    Function to evaluate whether a piece of text is all Latin characters, numbers or punctuation.

    Can be used to test whether a search phrase is suitable for parsing as a fulltext query, or whether it
    should be treated as an "icontains" or similarly language independent query filter.
    """
    if not text:
        return False
        
    return all(
        [
            (
                "LATIN" in unicodedata.name(x)
                or unicodedata.category(x).startswith("P")
                or unicodedata.category(x).startswith("N")
                or unicodedata.category(x).startswith("Z")
                or unicodedata.name(x) in ["HYPHEN-MINUS", "LOW LINE"]
            )
            for x in text
        ]
    )


class IIIFSearchParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        logger.debug("IIIF Search Parser being invoked")
        parser_context = parser_context or {}
        encoding = parser_context.get("encoding", settings.DEFAULT_CHARSET)
        try:
            decoded_stream = codecs.getreader(encoding)(stream)
            request_data = json.loads(decoded_stream.read())
            prefilter_kwargs = []
            postfilter_q = []
            filter_kwargs = {}
            search_string = request_data.get("fulltext", None)
            date_start = request_data.get("date_start", None)
            date_end = request_data.get("date_end", None)
            date_exact = request_data.get("date_exact", None)
            query_integer = request_data.get("integer", None)
            query_float = request_data.get("float", None)
            query_raw = request_data.get("raw", None)
            language = request_data.get("search_language", None)
            search_type = request_data.get("search_type", "websearch")
            facet_fields = request_data.get("facet_fields", None)
            contexts = request_data.get("contexts", None)
            contexts_all = request_data.get("contexts_all", None)
            madoc_identifiers = request_data.get("madoc_identifiers", None)
            iiif_identifiers = request_data.get("iiif_identifiers", None)
            facet_queries = request_data.get("facets", None)
            facet_on_manifests = request_data.get("facet_on_manifests", global_facet_on_manifests)
            facet_types = request_data.get("facet_types", global_facet_types)
            facet_languages = request_data.get("facet_languages")
            non_latin_fulltext = request_data.get("non_latin_fulltext", global_non_latin_fulltext)
            search_multiple_fields = request_data.get(
                "search_multiple_fields", global_search_multiple_fields
            )
            num_facets = request_data.get("number_of_facets", 10)
            metadata_fields = request_data.get("metadata_fields", None)
            autocomplete_type = request_data.get("autocomplete_type", None)
            autocomplete_subtype = request_data.get("autocomplete_subtype", None)
            autocomplete_query = request_data.get("autocomplete_query", None)
            if madoc_site_urn := request_madoc_site_urn(parser_context.get("request")):
                logger.debug(f"Got madoc site urn: {madoc_site_urn}")
                prefilter_kwargs.append(Q(**{f"madoc_id__startswith": madoc_site_urn}))
            if contexts:
                prefilter_kwargs.append(Q(**{f"contexts__id__in": contexts}))
            if contexts_all:
                for c in contexts_all:
                    prefilter_kwargs.append(Q(**{"contexts__id__iexact": c}))
            if madoc_identifiers:
                prefilter_kwargs.append(Q(**{f"madoc_id__in": madoc_identifiers}))
            if iiif_identifiers:
                prefilter_kwargs.append(Q(**{f"id__in": iiif_identifiers}))
            if search_string:
                if (non_latin_fulltext or is_latin(search_string)) and not search_multiple_fields:
                    # Search string is good candidate for fulltext query and we are not searching across multiple fields
                    if language:
                        filter_kwargs["indexables__search_vector"] = SearchQuery(
                            search_string, config=language, search_type=search_type
                        )
                    else:
                        filter_kwargs["indexables__search_vector"] = SearchQuery(
                            search_string, search_type=search_type
                        )
                else:
                    [
                        postfilter_q.append(
                            Q(  # Iterate the split words/chars to make the Q objects
                                **{f"indexables__indexable__icontains": split_search}
                            )
                        )
                        for split_search in search_string.split()
                    ]
            for p in [
                "type",
                "subtype",
                "language_iso639_2",
                "language_iso639_1",
                "language_display",
                "language_pg",
            ]:
                if request_data.get(p, None):
                    filter_kwargs[f"indexables__{p}__iexact"] = request_data[p]
            if query_raw and isinstance(query_raw, dict):
                for raw_k, raw_v in query_raw.items():
                    if raw_k.startswith(("indexables__", "type__", "madoc_id__", "id__")):
                        filter_kwargs[raw_k] = raw_v
            if query_float:
                if query_float.get("value"):
                    if query_float.get("operator", "exact") in ["exact", "gt", "lt", "gte", "lte"]:
                        filter_kwargs[
                            f"indexables__indexable_float__{query_float.get('operator', 'exact')}"
                        ] = query_float["value"]
            if query_integer:
                if query_integer.get("value"):
                    if query_integer.get("operator", "exact") in [
                        "exact",
                        "gt",
                        "lt",
                        "gte",
                        "lte",
                    ]:
                        filter_kwargs[
                            f"indexables__indexable_integer__{query_integer.get('operator', 'exact')}"
                        ] = query_integer["value"]
            if date_start:
                date_kwargs = date_q(value=date_start, date_query_type="start")
                if date_kwargs:
                    filter_kwargs.update(date_kwargs)
            if date_end:
                date_kwargs = date_q(value=date_end, date_query_type="end")
                if date_kwargs:
                    filter_kwargs.update(date_kwargs)
            if date_exact:
                date_kwargs = date_q(value=date_exact, date_query_type="exact")
                if date_kwargs:
                    filter_kwargs.update(date_kwargs)
            if facet_queries:
                postfilter_q += parse_facets(facet_queries=facet_queries)
            hits_filter_kwargs = {
                k.replace("indexables__", ""): v
                for k, v in filter_kwargs.items()
                if k.startswith("indexables")
            }
            if search_string:
                hits_filter_kwargs["search_string"] = search_string
            if language:
                hits_filter_kwargs["language"] = language
            if search_type:
                hits_filter_kwargs["search_type"] = search_type
            sort_order = request_data.get("ordering", {"ordering": "descending"})
            logger.info(f"Filter kwargs: {filter_kwargs}")
            return {
                "prefilter_kwargs": prefilter_kwargs,
                "filter_kwargs": filter_kwargs,
                "postfilter_kwargs": postfilter_q,
                "facet_fields": facet_fields,
                "hits_filter_kwargs": hits_filter_kwargs,
                "sort_order": sort_order,
                "facet_on_manifest": facet_on_manifests,
                "facet_types": facet_types,
                "facet_languages": facet_languages,
                "num_facets": num_facets,
                "metadata_fields": metadata_fields,
                "autocomplete_type": autocomplete_type,
                "autocomplete_subtype": autocomplete_subtype,
                "autocomplete_query": autocomplete_query,
            }
        except ValueError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))


def parse_and_configure_iiif_ingest(data, madoc_site_urn=None):
    """
    Will return an upgraded manifest and other properties needed by the ingest.

    Expects as input a dict with:

        {
        "casacde": Boolean,
        "cascade_canvases": Boolean,
        "contexts": List,
        "resource": IIIF Presentation API resource,
        "id": Madoc ID (string),
        "thumbnail": Thumbnail URI,
        }

    :param data:
    :param madoc_site_urn:
    :return:
    """
    _return = dict(
        cascade=data.get("cascade", False),
        cascade_canvases=data.get("cascade_canvases", False),
        resource_contexts=data.get("contexts", []),
        iiif3_resource=None,
        manifest=None,
        madoc_id=data.get("madoc_id", data.get("id")),
        madoc_thumbnail=data.get("thumbnail"),
        child=False,
        parent=None,
    )
    if madoc_site_urn:
        if not _return["madoc_id"].startswith(f"{madoc_site_urn}|"):
            _return["madoc_id"] = f"{madoc_site_urn}|{_return['madoc_id']}"
    if (iiif_resource := data.get("resource")) is not None:
        if iiif_resource.get("@context") == "http://iiif.io/api/presentation/2/context.json":
            iiif3 = upgrader.process_resource(iiif_resource, top=True)
            iiif3["@context"] = "http://iiif.io/api/presentation/3/context.json"
            _return["iiif3_resource"] = iiif3
        else:
            _return["iiif3_resource"] = iiif_resource
    if (iiif := _return.get("iiif3_resource")) is not None:
        _return["id"] = iiif.get("id")
        # Add self to context, this is so that for example, if constrain context to a specific object
        # it finds content _on_ that object, and not just on objects _within_ that object.
        if (iiif_type := iiif.get("type")) is not None:
            _return["resource_contexts"] += [{"id": _return["id"], "type": iiif_type}]
            _return["type"] = iiif_type
            if iiif_type == "Manifest":
                _return["manifest"] = iiif
    return _return


class IIIFCreateUpdateParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        logger.debug("IIIF Ingest Parser being invoked")
        parser_context = parser_context or {}
        encoding = parser_context.get("encoding", settings.DEFAULT_CHARSET)
        if madoc_site_urn := request_madoc_site_urn(parser_context["request"]._request):
            logger.info(f"Got a Madoc Site URN {madoc_site_urn}")
        else:
            logger.info("No Madoc Site URN")
        try:
            decoded_stream = codecs.getreader(encoding)(stream)
            request_data = json.loads(decoded_stream.read())
            logger.debug("We have JSON")
            if (overridden := parser_context.get("kwargs").get("data_override")) is not None:
                logger.debug("Overridden")
                return parse_and_configure_iiif_ingest(
                    data=overridden, madoc_site_urn=madoc_site_urn
                )
            else:
                logger.debug("Not overridden")
                parsed = parse_and_configure_iiif_ingest(
                    data=request_data, madoc_site_urn=madoc_site_urn
                )
                return parsed
        except ValueError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))
