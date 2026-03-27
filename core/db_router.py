class PrimaryReplicaRouter:
    PRIMARY = "default"
    REPLICA = "replica"

    PRIMARY_ONLY_APPS = frozenset([
        "token_blacklist",
        "rest_framework_simplejwt",
        "django_celery_results",
        "django_celery_beat",
    ])

    def db_for_read(self, model, **hints) -> str:
        if model._meta.app_label in self.PRIMARY_ONLY_APPS:
            return self.PRIMARY
        return self.REPLICA

    def db_for_write(self, model, **hints) -> str:
        return self.PRIMARY

    def allow_relation(self, obj1, obj2, **hints) -> bool:
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints) -> bool:
        return db == self.PRIMARY
