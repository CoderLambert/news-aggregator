from django.http import Http404, HttpResponse
from rest_framework.response import Response
from api.rss.http import RssAPIView
from api.rss.import_models import RssImportBatch
from api.rss.opml import MAX_BYTES, TooLarge, batch_data, confirm, export_opml, preview, retry_failed


class OpmlPreviewView(RssAPIView):
    def post(self, request):
        file = request.FILES.get('file')
        if file and file.size > MAX_BYTES:
            raise TooLarge
        return Response(preview(request.user, file.read(MAX_BYTES + 1) if file else b''), status=201)


class OpmlConfirmView(RssAPIView):
    def post(self, request):
        return Response(confirm(request.user, request.data), status=202)


class OpmlBatchView(RssAPIView):
    def get(self, request, pk):
        try:
            batch = RssImportBatch.objects.get(pk=pk, user=request.user)
        except RssImportBatch.DoesNotExist:
            raise Http404 from None
        return Response(batch_data(batch))

    def post(self, request, pk):
        return Response(retry_failed(request.user, pk, request.data), status=202)


class OpmlExportView(RssAPIView):
    def get(self, request):
        response = HttpResponse(export_opml(request.user), content_type='text/x-opml; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="subscriptions.opml"'
        return response
