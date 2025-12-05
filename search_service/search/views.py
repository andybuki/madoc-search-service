# Django Imports

import itertools
import logging
from collections import defaultdict

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import get_language
from django_filters import rest_framework as df_filters
from django_filters.rest_framework import DjangoFilterBackend

# DRF Imports
from rest_framework import generics, filters, status
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError, ParseError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.reverse import reverse

from .filters import IIIFSearchFilter, FacetListFilter, AutoCompleteFilter
from .indexable_utils import gen_indexables

# Local imports
from .models import Indexables, IIIFResource, Context
from .parsers import IIIFSearchParser, IIIFCreateUpdateParser
from .pagination import MadocPagination
from .prezi_upgrader import Upgrader
from .serializer_utils import MethodBasedSerializerMixin
from .serializers import (
    UserSerializer,
    IndexablesSerializer,
    IIIFSerializer,
    ContextSerializer,
    IIIFSearchSummarySerializer,
    CaptureModelSerializer,
    AutocompleteSerializer,
    IIIFCreateUpdateSerializer,
)
from .madoc_jwt import (
    request_madoc_site_urn,
)

# Globals
default_lang = get_language()
upgrader = Upgrader(flags={"default_lang": default_lang})
global_facet_on_manifests = settings.FACET_ON_MANIFESTS_ONLY
global_facet_types = ["metadata"]


logger = logging.getLogger(__name__)


@api_view(["GET"])
def api_root(request, format=None):
    return Response(
        {
            "iiif": reverse("search.api.iiifresource_list", request=request, format=format),
            "indexable": reverse(
                "search.api.indexables_list", request=request, format=format
            ),
            "contexts": reverse("search.api.context_list", request=request, format=format),
            "search": reverse("search.api.search", request=request, format=format),
        }
    )


class UserList(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class UserDetail(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class IIIFDetail(MethodBasedSerializerMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = IIIFResource.objects.all()
    serializer_class = IIIFSerializer
    serializer_mapping = {
        "get": IIIFSerializer,
        "put": IIIFCreateUpdateSerializer,
    }
    # permission_classes = [AllowAny]
    parser_classes = [IIIFCreateUpdateParser]

    def get_object(self):
        if madoc_site_urn := request_madoc_site_urn(self.request):
            logger.debug(f"Got madoc site urn: {madoc_site_urn}")
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            url_id = self.kwargs.get(lookup_url_kwarg)
            self.kwargs[lookup_url_kwarg] = f"{madoc_site_urn}|{url_id}"
        return super().get_object()


class IIIFList(MethodBasedSerializerMixin, generics.ListCreateAPIView):
    queryset = IIIFResource.objects.all().prefetch_related("contexts")
    serializer_class = IIIFSerializer
    serializer_mapping = {
        "get": IIIFSerializer,
        "post": IIIFCreateUpdateSerializer,
    }
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["madoc_id"]
    # permission_classes = [AllowAny]
    parser_classes = [IIIFCreateUpdateParser]


class ContextDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Context.objects.all()
    serializer_class = ContextSerializer
    lookup_field = "slug"


class ContextList(generics.ListCreateAPIView):
    queryset = Context.objects.all()
    serializer_class = ContextSerializer


class IndexablesDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Indexables.objects.all()
    serializer_class = IndexablesSerializer


class IndexablesList(generics.ListCreateAPIView):
    serializer_class = IndexablesSerializer
    filter_backends = [DjangoFilterBackend]
    queryset = Indexables.objects.all()
    filterset_fields = [
        "resource_id",
        "content_id",
        "iiif__madoc_id",
        "iiif__contexts__id",
        "type",
        "subtype",
    ]


class ContextFilterSet(df_filters.FilterSet):
    """
    Currently unused. Test filterset to change the filter field for contexts, e.g. to
    "cont"
    """

    cont = df_filters.filters.CharFilter(field_name="contexts__id", lookup_expr="iexact")

    class Meta:
        model = Context
        fields = ["cont"]


class ModelDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Indexables.objects.all()
    serializer_class = CaptureModelSerializer


class ModelList(generics.ListCreateAPIView):
    """
    List/Create API view for Indexables that are being created/listed
    """

    serializer_class = CaptureModelSerializer
    filter_backends = [DjangoFilterBackend]
    queryset = Indexables.objects.all()
    filterset_fields = [
        "resource_id",
        "content_id",
        "iiif__madoc_id",
        "iiif__contexts__id",
        "type",
        "subtype",
    ]

    def create(self, request, *args, **kwargs):
        """
        Override the .create() method on the rest-framework generic ListCreateAPIViewset
        """
        data = request.data
        good_results = []
        bad_results = []
        indexables = []
        if data.get("resource"):
            indexables = gen_indexables(data)
        if indexables:
            for indexable in indexables:
                serializer = self.get_serializer(data=indexable)  # Serialize the data
                serializer.is_valid(raise_exception=True)  # Check it's valid
                self.perform_create(serializer)  # Create the object
                if serializer.errors != {}:
                    bad_results.append(
                        (serializer.data, self.get_success_headers(serializer.data))
                    )
                else:
                    good_results.append(
                        (serializer.data, self.get_success_headers(serializer.data))
                    )
            return_status = status.HTTP_201_CREATED
            if len(good_results) > 0:
                if len(bad_results) > 0:
                    return_status = status.HTTP_206_PARTIAL_CONTENT
                return Response(
                    [res[0] for res in good_results],
                    status=return_status,
                    headers=good_results[-1][1],
                )
            raise ValidationError
        raise ParseError


class SearchBaseClass(viewsets.ReadOnlyModelViewSet):
    """
    BaseClass for Search Service APIs.
    """

    queryset = IIIFResource.objects.all().distinct().prefetch_related("contexts")
    serializer_class = IIIFSearchSummarySerializer
    parser_classes = [IIIFSearchParser]
    permission_classes = [AllowAny]


class IIIFSearch(SearchBaseClass):
    """
    Simple read only view for the IIIF data with methods for
    adding hits and generating facets for return in the results

    Uses a custom paginator to fit the Madoc model.
    """

    filter_backends = [IIIFSearchFilter]
    pagination_class = MadocPagination

    def get_facets(self, request):
        facet_summary = defaultdict(dict)
        # If we haven't been provided a list of facet fields via a POST
        # just generate the list by querying the unique list of metadata subtypes
        # Make a copy of the query so we aren't running the get_queryset logic every time
        facetable_queryset = self.filter_queryset(queryset=self.get_queryset())
        if request.data.get("facet_on_manifests", None):
            """
            Facet on IIIF objects where:

             1. They are associated (via the reverse relationship on `contexts`) with the queryset,
                and where the associated context is a manifest
             2. The object type is manifest

             In other words, give me all the manifests where they are associated with a manifest context
              that is related to the objects in the queryset. This manifest context should/will be
              themselves as manifests are associated with themselves as context.
            """
            facetable_q = self.queryset.filter(
                contexts__associated_iiif__madoc_id__in=facetable_queryset,
                contexts__type__iexact="manifest",
                type__iexact="manifest",
            ).distinct()
        else:
            """
            Otherwise, just create the facets on the objects that are in the queryset, rather than their
            containing manifest contexts.
            """
            facetable_q = facetable_queryset
        # if not request.data.get("facet_types", None):
        #     request.data["facet_types"] = ["metadata"]
        # if request.data.get("facet_fields"):
        #     facet_summary = (
        #         facetable_q.filter(
        #             indexables__type__in=request.data["facet_types"],
        #             indexables__subtype__in=request.data["facet_fields"],
        #         )
        #         .values("indexables__type", "indexables__subtype", "indexables__indexable")
        #         .annotate(n=models.Count("pk", distinct=True))
        #         .order_by("indexables__type", "indexables__subtype", "-n", "indexables__indexable")
        #     )
        # else:
        #     facet_summary = (
        #         facetable_q.filter(indexables__type__in=request.data["facet_types"])
        #         .values("indexables__type", "indexables__subtype", "indexables__indexable")
        #         .annotate(n=models.Count("pk", distinct=True))
        #         .order_by("indexables__type", "indexables__subtype", "-n", "indexables__indexable")
        #     )
        facet_filter_args = [
            models.Q(indexables__type__in=request.data.get("facet_types", ["metadata"])),
        ]
        if facet_fields := request.data.get("facet_fields"):
            facet_filter_args.append(models.Q(indexables__subtype__in=facet_fields))

        facet_languages = request.data.get("facet_languages")
        if facet_languages:
            facet_language_codes = set(map(lambda x: x.split("-")[0], facet_languages))
            iso639_1_codes = list(filter(lambda x: len(x) == 2, facet_language_codes))
            iso639_2_codes = list(filter(lambda x: len(x) == 3, facet_language_codes))
            # Always include indexables where no language is specified.
            # This will be cases where there it has neither iso639 field set.
            facet_language_filter = models.Q(
                indexables__language_iso639_1__isnull=True
            ) & models.Q(indexables__language_iso639_2__isnull=True)
            if iso639_1_codes:
                facet_language_filter |= models.Q(indexables__language_iso639_1__in=iso639_1_codes)
            if iso639_2_codes:
                facet_language_filter |= models.Q(indexables__language_iso639_2__in=iso639_2_codes)
            facet_filter_args.append(facet_language_filter)
            logger.debug(f"Filtering facets by languages: {facet_languages} (codes: {iso639_1_codes + iso639_2_codes})")

        # Check if we should include language info in facets (for debugging/advanced use)
        include_language = request.data.get("facet_include_language", False)

        if include_language:
            # Include language information in facet results
            facet_summary = (
                facetable_q.filter(*facet_filter_args)
                .values(
                    "indexables__type",
                    "indexables__subtype",
                    "indexables__indexable",
                    "indexables__language_iso639_1",
                )
                .annotate(n=models.Count("pk", distinct=True))
                .order_by("indexables__type", "indexables__subtype", "-n", "indexables__indexable")
            )
            grouped_facets = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
            truncate_to = request.data.get("num_facets", 10)
            truncated_facets = defaultdict(lambda: defaultdict(dict))
            # Turn annotated list of results into a deeply nested dict with language info
            for facet in facet_summary:
                lang = facet["indexables__language_iso639_1"] or "none"
                value = facet["indexables__indexable"]
                grouped_facets[facet["indexables__type"]][facet["indexables__subtype"]][value] = {
                    "count": facet["n"],
                    "language": lang,
                }
            # Take the deeply nested dict and truncate the leaves of the tree to just N keys.
            for facet_type, facet_subtypes in grouped_facets.items():
                for k, v in facet_subtypes.items():
                    truncated_facets[facet_type][k] = dict(itertools.islice(v.items(), truncate_to))
            return truncated_facets
        else:
            # Standard facet format (backward compatible)
            facet_summary = (
                facetable_q.filter(*facet_filter_args)
                .values("indexables__type", "indexables__subtype", "indexables__indexable")
                .annotate(n=models.Count("pk", distinct=True))
                .order_by("indexables__type", "indexables__subtype", "-n", "indexables__indexable")
            )
            grouped_facets = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
            truncate_to = request.data.get("num_facets", 10)
            truncated_facets = defaultdict(lambda: defaultdict(dict))
            # Turn annotated list of results into a deeply nested dict
            for facet in facet_summary:
                grouped_facets[facet["indexables__type"]][facet["indexables__subtype"]][
                    facet["indexables__indexable"]
                ] = facet["n"]
            # Take the deeply nested dict and truncate the leaves of the tree to just N keys.
            for facet_type, facet_subtypes in grouped_facets.items():
                for k, v in facet_subtypes.items():
                    truncated_facets[facet_type][k] = dict(itertools.islice(v.items(), truncate_to))
            return truncated_facets

    def list(self, request, *args, **kwargs):
        resp = super().list(request, *args, **kwargs)
        resp.data.update({"facets": self.get_facets(request=request)})
        reverse_sort = False
        if request.data.get("sort_order", None):
            if (direction := request.data["sort_order"].get("direction")) is not None:
                if direction == "descending":
                    logger.debug("Descending")
                    reverse_sort = True
        resp.data["results"] = sorted(
            resp.data["results"],
            key=lambda k: (k.get("sortk"),),
            reverse=reverse_sort,
        )
        return resp


class Facets(SearchBaseClass):
    """
    Simple read only view to return a list of facet fields
    """

    filter_backends = [FacetListFilter]

    def get_facet_list(self, request):
        facet_dict = defaultdict(list)
        # If we haven't been provided a list of facet fields via a POST
        # just generate the list by querying the unique list of metadata subtypes
        # Make a copy of the query so we aren't running the get_queryset logic every time
        facetable_queryset = self.filter_queryset(queryset=self.get_queryset())
        if request.data.get("facet_on_manifests", None):
            """
            Facet on IIIF objects where:

             1. They are associated (via the reverse relationship on `contexts`) with the queryset,
                and where the associated context is a manifest
             2. The object type is manifest

             In other words, give me all the manifests where they are associated with a manifest
             context that is related to the objects in the queryset. This manifest context
             should/will be themselves as manifests are associated with themselves as context.
            """
            facetable_q = IIIFResource.objects.filter(
                contexts__associated_iiif__madoc_id__in=facetable_queryset,
                contexts__type__iexact="manifest",
                type__iexact="manifest",
            ).distinct()
        else:
            """
            Otherwise, just create the facets on the objects that are in the queryset,
            rather than their containing manifest contexts.
            """
            facetable_q = facetable_queryset
        facet_fields = []
        if not request.data.get("facet_types", None):
            request.data["facet_types"] = ["metadata"]
        for facet_type in request.data["facet_types"]:
            for t in (
                facetable_q.filter(indexables__type__iexact=facet_type)
                .values("indexables__subtype")
                .distinct()
            ):
                for _, v in t.items():
                    if v and v != "":
                        facet_fields.append((facet_type, v))
        facet_l = sorted(list(set(facet_fields)))
        for i in facet_l:
            facet_dict[i[0]].append(i[1])
        return facet_dict

    def list(self, request, *args, **kwargs):
        response = super(Facets, self).list(request, args, kwargs)
        response.data = self.get_facet_list(request=request)
        return response


class Autocomplete(SearchBaseClass):
    queryset = Indexables.objects.all()
    serializer_class = AutocompleteSerializer
    filter_backends = [AutoCompleteFilter]

    def list(self, request, *args, **kwargs):
        facetable_queryset = self.filter_queryset(self.get_queryset().all())
        raw_data = (
            facetable_queryset.values("indexable")
            .distinct()
            .annotate(n=models.Count("pk", distinct=True))
            .order_by("-n")[:10]
        )
        return_data = {
            "results": [{"id": x.get("indexable"), "text": x.get("indexable")} for x in raw_data]
        }
        return Response(data=return_data)
