from django.http import HttpResponse
from django.views.generic import ListView, DetailView
from django.views.generic.detail import BaseDetailView
from raw.models import RawCouncilAgenda, RawMember, RawCommittee
from raw.names import NameMatcher, MemberName


class RawCouncilAgendaListView(ListView):
    model = RawCouncilAgenda
    template_name = 'raw/agenda_list.html'
    paginate_by = 25


class RawCouncilAgendaDetailView(DetailView):
    model = RawCouncilAgenda
    slug_field = 'uid'
    template_name = 'raw/agenda_detail.html'

    def get_context_data(self, **kwargs):
        context = super(RawCouncilAgendaDetailView, self).get_context_data(**kwargs)
        parser = self.object.get_parser()
        context['parser'] = parser
        all_members = RawMember.objects.all()
        names = [(xx.get_name_object(), xx) for xx in all_members]
        matcher = NameMatcher(names)
        questions = []
        for q in parser.questions:
            name = MemberName(q.asker)
            match = matcher.match(name)
            obj = (q, match)
            questions.append(obj)
        context['questions'] = questions
        return context


class RawCouncilAgendaSourceView(BaseDetailView):
    model = RawCouncilAgenda
    slug_field = 'uid'

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return HttpResponse(self.object.get_source())


class RawMemberListView(ListView):
    model = RawMember
    template_name = 'raw/member_list.html'
    paginate_by = 25


class RawMemberDetailView(DetailView):
    model = RawMember
    template_name = 'raw/member_detail.html'

    def get_context_data(self, **kwargs):
        context = super(RawMemberDetailView, self).get_context_data(**kwargs)
        fields = ['gender', 'year_of_birth', 'place_of_birth', 'homepage']
        context['fields'] = []
        for f in fields:
            res = {'label': f, 'value': getattr(self.object, f, '')}
            context['fields'].append(res)
        return context


class RawCommitteeListView(ListView):
    model = RawCommittee
    template_name = 'raw/committee_list.html'
    paginate_by = 25


class RawCommitteeDetailView(DetailView):
    model = RawCommittee
    template_name = 'raw/committee_detail.html'
