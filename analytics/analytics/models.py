from django.contrib.postgres.fields import ArrayField
from django.db import models


class NodeCapacityType(models.TextChoices):
    SPOT = "spot"
    ON_DEMAND = "on-demand"


class Job(models.Model):
    # Core job fields
    job_id = models.PositiveBigIntegerField(primary_key=True)
    project_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=128)
    started_at = models.DateTimeField()
    duration = models.DurationField()
    ref = models.CharField(max_length=256)
    tags = ArrayField(base_field=models.CharField(max_length=32), default=list)
    package_name = models.CharField(max_length=128)

    # Whether this job ran in the cluster or not
    aws = models.BooleanField(default=True, null=True)

    # Kubernetes specific data (will be null for non-aws jobs)
    cpu_request = models.FloatField(null=True, default=None)
    cpu_limit = models.FloatField(null=True, default=None)
    memory_request = models.PositiveBigIntegerField(null=True, default=None)
    memory_limit = models.PositiveBigIntegerField(null=True, default=None)

    # Node info (will be null for non-aws jobs)
    node_name = models.CharField(max_length=64, null=True, default=None)
    node_system_uuid = models.UUIDField(null=True, default=None)
    node_cpu = models.PositiveIntegerField(null=True, default=None)
    node_memory = models.PositiveIntegerField(null=True, default=None)
    node_capacity_type = models.CharField(
        max_length=12, choices=NodeCapacityType.choices, null=True, default=None
    )
    node_instance_type = models.CharField(max_length=32, null=True, default=None)
    node_instance_type_spot_price = models.FloatField(
        null=True,
        default=None,
        help_text=(
            "The price per hour (in USD) of the spot instnce this job ran on, at the time of"
            " running. If ever the job runs on an on-demand node, this field will be null."
        ),
    )

    # Extra data fields (null allowed to accomodate historical data)
    package_version = models.CharField(max_length=128, null=True)
    compiler_name = models.CharField(max_length=128, null=True)
    compiler_version = models.CharField(max_length=128, null=True)
    arch = models.CharField(max_length=128, null=True)
    package_variants = models.TextField(null=True)
    build_jobs = models.CharField(max_length=128, null=True)
    job_size = models.CharField(max_length=128, null=True)
    stack = models.CharField(max_length=128, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="unique-project-job-id", fields=["project_id", "job_id"]
            ),
            models.CheckConstraint(
                name="non-empty-package-name", check=~models.Q(package_name="")
            ),
        ]


class Timer(models.Model):
    job = models.ForeignKey(Job, related_name="timers", on_delete=models.CASCADE)
    name = models.CharField(max_length=256)
    time_total = models.FloatField()
    hash = models.CharField(max_length=128, null=True)
    cache = models.BooleanField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="unique-hash-name-job", fields=["hash", "name", "job"]
            ),
            # Ensure that if a timer name starts with a "." (internal timer), that cache and hash
            # are null, and that otherwise they are present
            models.CheckConstraint(
                name="internal-timer-consistent-hash-and-cache",
                check=(
                    models.Q(
                        name__startswith=".", hash__isnull=True, cache__isnull=True
                    )
                    | (
                        ~models.Q(name__startswith=".")
                        & models.Q(hash__isnull=False, cache__isnull=False)
                    )
                ),
            ),
        ]


class TimerPhase(models.Model):
    timer = models.ForeignKey(Timer, related_name="phases", on_delete=models.CASCADE)
    name = models.CharField(max_length=128)
    is_subphase = models.BooleanField(default=False)
    path = models.CharField(max_length=128)
    seconds = models.FloatField()
    count = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["path", "timer"], name="unique-phase-path"),
        ]


class ErrorTaxonomy(models.Model):
    job_id = models.PositiveBigIntegerField(primary_key=True)

    created = models.DateTimeField(auto_now_add=True)

    attempt_number = models.PositiveSmallIntegerField()
    retried = models.BooleanField()

    error_taxonomy = models.CharField(max_length=64)
    error_taxonomy_version = models.CharField(max_length=32)

    webhook_payload = models.JSONField(
        help_text="The JSON payload received from the GitLab job webhook."
    )
