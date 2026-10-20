"""Session/CSRF protected review surfaces with explicit owner projections."""
from django.contrib.auth import get_user_model
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from api.rss.http import RssAPIView
from api.rss.additions import pagination, request_key
from api.rss.recommendations import (candidates,candidate_data,submission_result,submit_recommendation,change_submission,decide_candidate)
from api.rss.review_models import PublicFeedSubmission, RssReviewerGrant
from api.rss.review_permissions import review_authority, require_superuser, change_reviewer, reviewer_data
from api.rss.subscriptions import engine_identity


class ReviewerView(RssAPIView):
    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if review_authority(request.user) is None: raise PermissionDenied('需要频道审核权限。')


def paged(rows,request,serialize):
    page,size=pagination(request.query_params)
    return {'results':[serialize(row) for row in rows[(page-1)*size:page*size]],'count':rows.count(),'page':page,'page_size':size}


class MyRecommendationsView(RssAPIView):
    def get(self,request):
        rows=PublicFeedSubmission.objects.filter(user=request.user,candidate__in=candidates()).select_related('candidate__binding','candidate__category','candidate__decision').order_by('-created_at','-pk')
        return Response(paged(rows,request,lambda row:submission_result(row,request.user)))
    def post(self,request):
        return Response(submit_recommendation(request.user,dict(request.data),request_key(request)),status=202)


class MyRecommendationActionView(RssAPIView):
    def post(self,request,pk):
        return Response(change_submission(request.user,pk,dict(request.data),request_key(request)))


class RecommendationsView(ReviewerView):
    def get(self,request):
        from django.db.models import Q,Count
        rows=candidates()
        q=request.query_params.get('q','').strip()
        if len(q)>200: raise ValidationError('搜索内容最多200字符。')
        if q: rows=rows.filter(Q(name__icontains=q)|Q(binding__canonical_feed_url__icontains=q)|Q(binding__effective_feed_url__icontains=q))
        counts={s:0 for s in ['pending','approved','rejected','withdrawn','published']}
        for row in rows.order_by().values('state').annotate(total=Count('pk')): counts[row['state']]=row['total']
        state=request.query_params.get('status','pending')
        if state not in {*counts,'all'}: raise ValidationError('无效的审核状态。')
        if state!='all': rows=rows.filter(state=state)
        result=paged(rows.order_by('-created_at','pk'),request,lambda row:candidate_data(row,viewer=request.user))
        result['counts']=counts
        return Response(result)


class RecommendationDetailView(ReviewerView):
    def get(self,request,pk):
        row=candidates().filter(pk=pk).first()
        if row is None: raise Http404
        result=candidate_data(row,viewer=request.user)
        result['notes']=list(row.submissions.filter(withdrawn_at__isnull=True).values('note','created_at')[:50])
        result['history']=list(row.events.filter(action__in=['approve','reject','register']).values('action','candidate_version','reason','created_at'))
        return Response(result)


class RecommendationDecisionView(ReviewerView):
    def post(self,request,pk):
        return Response(decide_candidate(request.user,pk,dict(request.data),request_key(request)))


class ReviewersView(RssAPIView):
    def get(self,request):
        require_superuser(request.user)
        instance,_=engine_identity()
        name=request.query_params.get('username')
        if name is not None:
            if not name or len(name)>150: raise ValidationError('请输入准确用户名。')
            user=get_user_model().objects.filter(username=name,is_active=True,is_superuser=False).first()
            if user is None: return Response({'results':[]})
            grant=RssReviewerGrant.objects.filter(user=user,engine_instance_uuid=instance).first()
            return Response({'results':[reviewer_data(grant) if grant else {'id':None,'username':user.username,'active':False,'version':None}]})
        rows=RssReviewerGrant.objects.filter(engine_instance_uuid=instance).select_related('user').order_by('pk')
        return Response(paged(rows,request,reviewer_data))
    def post(self,request):
        if set(request.data)!={'username','expected_version'}: raise ValidationError('请提供用户名和当前版本。')
        return Response(change_reviewer(request.user,request.data['username'],True,request.data['expected_version'],request_key(request)),status=201)


class RevokeReviewerView(RssAPIView):
    def post(self,request,pk):
        require_superuser(request.user)
        if set(request.data)!={'expected_version'}: raise ValidationError('请提供当前版本。')
        instance,_=engine_identity()
        grant=RssReviewerGrant.objects.filter(pk=pk,engine_instance_uuid=instance).select_related('user').first()
        if grant is None: raise Http404
        return Response(change_reviewer(request.user,grant.user.username,False,request.data['expected_version'],request_key(request)))


class RecommendationVerificationView(ReviewerView):
    def post(self,request,pk):
        from api.rss.recommendations import verify_candidate
        return Response(verify_candidate(request.user,pk,dict(request.data),request_key(request)),status=202)
