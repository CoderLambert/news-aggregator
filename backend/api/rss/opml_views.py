from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.utils.http import content_disposition_header
from rest_framework.response import Response
from api.rss.http import RssAPIView
from api.rss.import_models import RssImportBatch
from api.rss.opml import MAX_BYTES, TooLarge, batch_data, confirm, export_opml, preview, retry_failed, remove_batch, control_batch


class OpmlPreviewView(RssAPIView):
    def post(self, request):
        file = request.FILES.get('file')
        if file and file.size > MAX_BYTES:
            raise TooLarge
        organize = request.data.get('organize_existing', False)
        only = request.data.get('organization_only', False)
        if organize not in (True, False, 'true', 'false') or only not in (True, False, 'true', 'false'):
            from rest_framework.exceptions import ValidationError
            raise ValidationError('整理选项须为布尔值。')
        organize, only = organize in (True, 'true'), only in (True, 'true')
        if only and (file or not organize):
            from rest_framework.exceptions import ValidationError
            raise ValidationError('仅整理已有订阅时请勿上传文件，并开启整理选项。')
        return Response(preview(request.user, file.read(MAX_BYTES + 1) if file else b'',
            file.name if file else '已有未分组订阅', organize_existing=organize,
            organization_only=only), status=201)


class OpmlConfirmView(RssAPIView):
    def post(self, request):
        return Response(confirm(request.user, request.data), status=202)


class OpmlBatchView(RssAPIView):
    def get(self, request, pk):
        try:
            batch = RssImportBatch.objects.defer('file_content').get(pk=pk, user=request.user)
        except RssImportBatch.DoesNotExist:
            raise Http404 from None
        return Response(batch_data(batch))

    def delete(self, request, pk):
        return Response(remove_batch(request.user, pk))

    def patch(self, request, pk):
        return Response(control_batch(request.user, pk, request.data))

    def post(self, request, pk):
        return Response(retry_failed(request.user, pk, request.data), status=202)


class OpmlExportView(RssAPIView):
    def get(self, request):
        response = HttpResponse(export_opml(request.user), content_type='text/x-opml; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="subscriptions.opml"'
        return response


class OpmlHistoryView(RssAPIView):
    def get(self, request):
        batches = RssImportBatch.objects.filter(user=request.user).defer('file_content').order_by('-created_at', '-pk')
        paginator = Paginator(batches, 20)
        page = paginator.get_page(request.query_params.get('page', '1'))
        return Response({'count': paginator.count, 'page': page.number,
                         'has_next': page.has_next(),
                         'results': [batch_data(batch, include_items=False) for batch in page]})


class OpmlFileView(RssAPIView):
    def get(self, request, pk):
        try:
            batch = RssImportBatch.objects.get(pk=pk, user=request.user)
        except RssImportBatch.DoesNotExist:
            raise Http404 from None
        if batch.file_content is None:
            raise Http404
        response = HttpResponse(bytes(batch.file_content), content_type='application/octet-stream')
        response['Content-Disposition'] = content_disposition_header(True, batch.filename or 'subscriptions.opml')
        response['X-Content-Type-Options'] = 'nosniff'
        return response
