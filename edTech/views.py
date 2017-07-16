from django.shortcuts 		import get_object_or_404, render
from django.http 			import HttpResponse, Http404, HttpResponseRedirect
from django.template 		import loader
from django.urls 			import reverse
from django.views 			import generic
from django.views.generic 	import TemplateView
# Create your views here.

def index(request):
    return render(request, 'index.html')