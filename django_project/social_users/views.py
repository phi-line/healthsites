# -*- coding: utf-8 -*-
import logging
import json

LOG = logging.getLogger(__name__)

from braces.views import LoginRequiredMixin
from core.utilities import extract_time
from datetime import datetime
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Max
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, View
from localities.models import Locality, LocalityArchive, ValueArchive
from localities.utils import extract_updates
from social_users.models import Profile
from social_users.utils import get_profile


class UserProfilePage(LoginRequiredMixin, TemplateView):
    template_name = 'social_users/profilepage.html'

    def get_context_data(self, *args, **kwargs):
        context = super(UserProfilePage, self).get_context_data(*args, **kwargs)
        context['auths'] = [
            auth.provider for auth in self.request.user.social_auth.all()
            ]
        return context


class ProfilePage(TemplateView):
    template_name = 'social_users/profile.html'

    def get_context_data(self, *args, **kwargs):
        """
        *debug* toggles GoogleAnalytics support on the main page
        """

        user = get_object_or_404(User, username=kwargs["username"])
        user = get_profile(user)
        context = super(ProfilePage, self).get_context_data(*args, **kwargs)
        context['user'] = user
        return context


class UserSigninPage(TemplateView):
    template_name = 'social_users/signinpage.html'


class LogoutUser(View):
    def get(self, request, *args, **kwargs):
        auth_logout(request)
        return HttpResponseRedirect('/')


def save_profile(backend, user, response, *args, **kwargs):
    url = None
    if backend.name == 'facebook':
        url = "http://graph.facebook.com/%s/picture?type=large" % response['id']
    if backend.name == 'twitter':
        url = response.get('profile_image_url', '').replace('_normal', '')
    if backend.name == 'google-oauth2':
        url = response['image'].get('url')
    # get old user
    if kwargs['is_new']:
        if 'username' in kwargs['details']:
            new_username = kwargs['details']['username']
            new_username = new_username.replace(" ", "")
            if user.username != new_username:
                try:
                    old_username = user.username
                    user = User.objects.get(username=new_username)
                    User.objects.get(username=old_username).delete()
                except User.DoesNotExist:
                    pass
    try:
        profile = Profile.objects.get(user=user)
    except Profile.DoesNotExist:
        profile = Profile(user=user)
    if url:
        profile.profile_picture = url
    profile.save()
    return {'user': user}


def user_updates(user, date):
    updates = []
    try:
        # from locality archive
        updates_temp = LocalityArchive.objects.filter(changeset__social_user=user).filter(
            changeset__created__lt=date).order_by(
            '-changeset__created').values(
            'changeset', 'changeset__created', 'changeset__social_user__username', 'version').annotate(
            edit_count=Count('changeset'), locality_id=Max('object_id'))[:15]
        for update in updates_temp:
            updates.append(update)
        # from value archive
        updates_temp = ValueArchive.objects.filter(changeset__social_user=user).filter(
            changeset__created__lt=date).filter(version__gt=1).order_by(
            '-changeset__created').values(
            'changeset', 'changeset__created', 'changeset__social_user__username', 'version').annotate(
            edit_count=Count('changeset'), locality_id=Max('locality_id'))[:15]
        for update in updates_temp:
            updates.append(update)
        # from locality changeset
        updates_temp = Locality.objects.filter(changeset__social_user=user).filter(
            changeset__created__lt=date).order_by(
            '-changeset__created').values(
            'changeset', 'changeset__created', 'changeset__social_user__username', 'version').annotate(
            edit_count=Count('changeset'), locality_id=Max('id'))[:15]
        for update in updates_temp:
            updates.append(update)
        updates.sort(key=extract_time, reverse=True)
    except LocalityArchive.DoesNotExist:
        pass

    output = []
    prev_changeset = 0
    for update in updates:
        if prev_changeset != update['changeset__created']:
            output.append(update)
            profile = get_profile(User.objects.get(username=update['changeset__social_user__username']))
            update['nickname'] = profile.screen_name
            if update['edit_count'] > 1 and update['version'] == 2:
                update['version'] = 1
        prev_changeset = update['changeset__created']
    return output[:20]


def get_user_updates(request):
    if request.method == 'GET':
        date = request.GET.get('date')
        user = request.GET.get('user')
        if not date:
            date = datetime.now()
        user = get_object_or_404(User, username=user)
        last_updates = user_updates(user, date)
        updates = extract_updates(last_updates)
        result = {}
        result['last_update'] = updates
        result = json.dumps(result, cls=DjangoJSONEncoder)

    return HttpResponse(result, content_type='application/json')
