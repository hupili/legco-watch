from __future__ import absolute_import
import os
from celery import Celery
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'legcowatch.settings')

app = Celery('legcowatch', broker='amqp://postgres:e8aVqxwaKVXMfBT\q@localhost:5432//')
#app = Celery('legcowatch', broker='amqp://guest:guest@rabbitmq:5672//')
#app = Celery('legcowatch', broker='amqp://postgres:8y8st657@localhost:5432//')
#app = Celery('legcowatch', broker='amqp://')

app.config_from_object('django.conf:settings')
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@app.task
def add(x, y):
    return x + y


@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
