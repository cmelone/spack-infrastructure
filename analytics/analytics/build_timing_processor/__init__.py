import json
from datetime import timedelta

import gitlab
import sentry_sdk
from celery import shared_task
from dateutil.parser import isoparse
from django.conf import settings
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import Project, ProjectJob

from analytics import setup_gitlab_job_sentry_tags
from analytics.build_timing_processor.build_timings import create_build_timings
from analytics.build_timing_processor.prometheus import (
    PrometheusClient,
    annotate_job_with_prometheus_data,
)
from analytics.models import Job


def create_job(gl: gitlab.Gitlab, project: Project, gljob: ProjectJob) -> Job:
    # This is one way to determine if a job ran in the cluster or not
    aws = None
    if gljob.runner is not None:
        # For various reasons, sometimes the runner is missing
        try:
            aws = "aws" in gl.runners.get(gljob.runner["id"]).tag_list
        except GitlabGetError as exc:
            if exc.error_message != "404 Not found":
                raise

    # Create base fields on job that are independent of where it ran
    job = Job(
        job_id=gljob.get_id(),
        project_id=project.get_id(),
        name=gljob.name,
        started_at=isoparse(gljob.started_at),
        duration=timedelta(seconds=gljob.duration),
        ref=gljob.ref,
        tags=gljob.tag_list,
        aws=aws,
    )

    # If ran in cluster, get remaining job data from prometheus
    if job.aws:
        client = PrometheusClient(settings.SPACK_PROMETHEUS_ENDPOINT)
        annotate_job_with_prometheus_data(job=job, client=client)

    # Save and return new job
    job.save()
    return job


@shared_task(name="upload_build_timings")
def upload_build_timings(job_input_data_json: str):
    # Read input data and extract params
    job_input_data = json.loads(job_input_data_json)
    setup_gitlab_job_sentry_tags(job_input_data)

    # Retrieve project and job from gitlab API
    gl = gitlab.Gitlab(settings.GITLAB_ENDPOINT, settings.GITLAB_TOKEN)
    gl_project = gl.projects.get(job_input_data["project_id"])
    gl_job = gl_project.jobs.get(job_input_data["build_id"])

    # Get or create job record
    job = create_job(gl, gl_project, gl_job)
    create_build_timings(job, gl_job)
