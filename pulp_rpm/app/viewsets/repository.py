from gettext import gettext as _

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.serializers import ValidationError as DRFValidationError

from pulpcore.plugin.actions import ModifyRepositoryActionMixin
from pulpcore.plugin.models import RepositoryVersion
from pulpcore.plugin.tasking import dispatch
from pulpcore.plugin.serializers import (
    AsyncOperationResponseSerializer,
)
from pulpcore.plugin.util import extract_pk
from pulpcore.plugin.viewsets import (
    DistributionViewSet,
    NamedModelViewSet,
    OperationPostponedResponse,
    PublicationViewSet,
    RemoteViewSet,
    RepositoryVersionViewSet,
    RepositoryViewSet,
    RolesMixin,
)

from pulp_rpm.app import tasks
from pulp_rpm.app.constants import SYNC_POLICIES
from pulp_rpm.app.models import (
    RpmDistribution,
    RpmPublication,
    RpmRemote,
    RpmRepository,
    UlnRemote,
)
from pulp_rpm.app.serializers import (
    CopySerializer,
    RpmDistributionSerializer,
    RpmPublicationSerializer,
    RpmRemoteSerializer,
    RpmRepositorySerializer,
    RpmRepositorySyncURLSerializer,
    UlnRemoteSerializer,
)


class RpmRepositoryViewSet(RepositoryViewSet, ModifyRepositoryActionMixin, RolesMixin):
    """
    A ViewSet for RpmRepository.
    """

    endpoint_name = "rpm"
    queryset = RpmRepository.objects.exclude(user_hidden=True)
    serializer_class = RpmRepositorySerializer
    queryset_filtering_required_permission = "rpm.view_rpmrepository"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": ["authenticated"],
                "effect": "allow",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_remote_param_model_or_domain_or_obj_perms:rpm.view_rpmremote",
                    "has_model_or_domain_perms:rpm.add_rpmrepository",
                ],
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.change_rpmrepository",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                    "has_remote_param_model_or_domain_or_obj_perms:rpm.view_rpmremote",
                ],
            },
            {
                "action": ["modify"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.modify_content_rpmrepository",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.delete_rpmrepository",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["sync"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.sync_rpmrepository",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                    "has_remote_param_model_or_domain_or_obj_perms:rpm.view_rpmremote",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.manage_roles_rpmrepository",
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "rpm.rpmrepository_owner"},
            }
        ],
    }

    LOCKED_ROLES = {
        "rpm.rpmrepository_owner": [
            "rpm.change_rpmrepository",
            "rpm.delete_rpmrepository",
            "rpm.delete_rpmrepository_version",
            "rpm.manage_roles_rpmrepository",
            "rpm.modify_content_rpmrepository",
            "rpm.repair_rpmrepository",
            "rpm.sync_rpmrepository",
            "rpm.view_rpmrepository",
        ],
        "rpm.rpmrepository_creator": [
            "rpm.add_rpmrepository",
        ],
        "rpm.rpmrepository_viewer": [
            "rpm.view_rpmrepository",
        ],
        # Here are defined plugin-wide `LOCKED_ROLES`
        "rpm.admin": [
            "rpm.add_rpmalternatecontentsource",
            "rpm.add_rpmdistribution",
            "rpm.add_rpmpublication",
            "rpm.add_rpmremote",
            "rpm.add_rpmrepository",
            "rpm.add_ulnremote",
            "rpm.change_rpmalternatecontentsource",
            "rpm.change_rpmdistribution",
            "rpm.change_rpmremote",
            "rpm.change_rpmrepository",
            "rpm.change_ulnremote",
            "rpm.delete_rpmalternatecontentsource",
            "rpm.delete_rpmdistribution",
            "rpm.delete_rpmpublication",
            "rpm.delete_rpmremote",
            "rpm.delete_rpmrepository",
            "rpm.delete_rpmrepository_version",
            "rpm.delete_ulnremote",
            "rpm.manage_roles_rpmalternatecontentsource",
            "rpm.manage_roles_rpmdistribution",
            "rpm.manage_roles_rpmpublication",
            "rpm.manage_roles_rpmremote",
            "rpm.manage_roles_rpmrepository",
            "rpm.manage_roles_ulnremote",
            "rpm.modify_content_rpmrepository",
            "rpm.refresh_rpmalternatecontentsource",
            "rpm.repair_rpmrepository",
            "rpm.sync_rpmrepository",
            "rpm.view_rpmalternatecontentsource",
            "rpm.view_rpmdistribution",
            "rpm.view_rpmpublication",
            "rpm.view_rpmremote",
            "rpm.view_rpmrepository",
            "rpm.view_ulnremote",
        ],
        "rpm.viewer": [
            "rpm.view_rpmalternatecontentsource",
            "rpm.view_rpmdistribution",
            "rpm.view_rpmpublication",
            "rpm.view_rpmremote",
            "rpm.view_rpmrepository",
            "rpm.view_ulnremote",
        ],
    }

    @extend_schema(
        description="Trigger an asynchronous task to sync RPM content.",
        summary="Sync from remote",
        responses={202: AsyncOperationResponseSerializer},
    )
    @action(detail=True, methods=["post"], serializer_class=RpmRepositorySyncURLSerializer)
    def sync(self, request, pk):
        """
        Dispatches a sync task.
        """
        repository = self.get_object()
        serializer = RpmRepositorySyncURLSerializer(
            data=request.data, context={"request": request, "repository_pk": pk}
        )
        serializer.is_valid(raise_exception=True)
        remote = serializer.validated_data.get("remote", repository.remote)
        mirror = serializer.validated_data.get("mirror")
        sync_policy = serializer.validated_data.get("sync_policy")
        skip_types = serializer.validated_data.get("skip_types")
        optimize = serializer.validated_data.get("optimize")

        if not sync_policy:
            sync_policy = SYNC_POLICIES.ADDITIVE if not mirror else SYNC_POLICIES.MIRROR_COMPLETE

        # validate some invariants that involve repository-wide settings.
        if sync_policy in (SYNC_POLICIES.MIRROR_COMPLETE, SYNC_POLICIES.MIRROR_CONTENT_ONLY):
            err_msg = (
                "Cannot use '{}' in combination with a 'mirror_complete' or "
                "'mirror_content_only' sync policy."
            )
            if repository.retain_package_versions > 0:
                raise DRFValidationError(err_msg.format("retain_package_versions"))

        if sync_policy == SYNC_POLICIES.MIRROR_COMPLETE:
            err_msg = "Cannot use '{}' in combination with a 'mirror_complete' sync policy."
            if repository.autopublish:
                raise DRFValidationError(err_msg.format("autopublish"))
            if skip_types:
                raise DRFValidationError(err_msg.format("skip_types"))

        result = dispatch(
            tasks.synchronize,
            shared_resources=[remote],
            exclusive_resources=[repository],
            kwargs={
                "sync_policy": sync_policy,
                "remote_pk": str(remote.pk),
                "repository_pk": str(repository.pk),
                "skip_types": skip_types,
                "optimize": optimize,
            },
        )
        return OperationPostponedResponse(result, request)


class RpmRepositoryVersionViewSet(RepositoryVersionViewSet):
    """
    RpmRepositoryVersion represents a single rpm repository version.
    """

    parent_viewset = RpmRepositoryViewSet

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_repository_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_repository_model_or_domain_or_obj_perms:rpm.delete_rpmrepository",
                    "has_repository_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_repository_model_or_domain_or_obj_perms:rpm.delete_rpmrepository_version",
                    "has_repository_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["repair"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_repository_model_or_domain_or_obj_perms:rpm.repair_rpmrepository",
                    "has_repository_model_or_domain_or_obj_perms:rpm.view_rpmrepository",
                ],
            },
        ],
    }


class RpmRemoteViewSet(RemoteViewSet, RolesMixin):
    """
    A ViewSet for RpmRemote.
    """

    endpoint_name = "rpm"
    queryset = RpmRemote.objects.all()
    serializer_class = RpmRemoteSerializer
    queryset_filtering_required_permission = "rpm.view_rpmremote"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": ["authenticated"],
                "effect": "allow",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.view_rpmremote",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_perms:rpm.add_rpmremote",
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.change_rpmremote",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmremote",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.delete_rpmremote",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmremote",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.manage_roles_rpmremote",
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "rpm.rpmremote_owner"},
            }
        ],
    }

    LOCKED_ROLES = {
        "rpm.rpmremote_owner": [
            "rpm.change_rpmremote",
            "rpm.delete_rpmremote",
            "rpm.manage_roles_rpmremote",
            "rpm.view_rpmremote",
        ],
        "rpm.rpmremote_creator": [
            "rpm.add_rpmremote",
        ],
        "rpm.rpmremote_viewer": [
            "rpm.view_rpmremote",
        ],
    }


class UlnRemoteViewSet(RemoteViewSet, RolesMixin):
    """
    A ViewSet for UlnRemote.
    """

    endpoint_name = "uln"
    queryset = UlnRemote.objects.all()
    serializer_class = UlnRemoteSerializer
    queryset_filtering_required_permission = "rpm.view_ulnremote"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": ["authenticated"],
                "effect": "allow",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.view_ulnremote",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_perms:rpm.add_ulnremote",
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.change_ulnremote",
                    "has_model_or_domain_or_obj_perms:rpm.view_ulnremote",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.delete_ulnremote",
                    "has_model_or_domain_or_obj_perms:rpm.view_ulnremote",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.manage_roles_ulnremote",
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "rpm.ulnremote_owner"},
            }
        ],
    }

    LOCKED_ROLES = {
        "rpm.ulnremote_owner": [
            "rpm.change_ulnremote",
            "rpm.delete_ulnremote",
            "rpm.manage_roles_ulnremote",
            "rpm.view_ulnremote",
        ],
        "rpm.ulnremote_creator": [
            "rpm.add_ulnremote",
        ],
        "rpm.ulnremote_viewer": [
            "rpm.view_ulnremote",
        ],
    }


class RpmPublicationViewSet(PublicationViewSet, RolesMixin):
    """
    ViewSet for Rpm Publications.
    """

    endpoint_name = "rpm"
    queryset = RpmPublication.objects.exclude(complete=False)
    serializer_class = RpmPublicationSerializer
    queryset_filtering_required_permission = "rpm.view_rpmpublication"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": ["authenticated"],
                "effect": "allow",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.view_rpmpublication",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_perms:rpm.add_rpmpublication",
                    "has_repo_or_repo_ver_param_model_or_domain_or_obj_perms:"
                    "rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.delete_rpmpublication",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmpublication",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.manage_roles_rpmpublication",
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "rpm.rpmpublication_owner"},
            }
        ],
    }

    LOCKED_ROLES = {
        "rpm.rpmpublication_owner": [
            "rpm.delete_rpmpublication",
            "rpm.manage_roles_rpmpublication",
            "rpm.view_rpmpublication",
        ],
        "rpm.rpmpublication_creator": [
            "rpm.add_rpmpublication",
        ],
        "rpm.rpmpublication_viewer": [
            "rpm.view_rpmpublication",
        ],
    }

    @extend_schema(
        description="Trigger an asynchronous task to create a new RPM content publication.",
        responses={202: AsyncOperationResponseSerializer},
    )
    def create(self, request):
        """
        Dispatches a publish task.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repository_version = serializer.validated_data.get("repository_version")
        repository = RpmRepository.objects.get(pk=repository_version.repository.pk)

        checkpoint = serializer.validated_data.get("checkpoint")
        checksum_type = serializer.validated_data.get("checksum_type", repository.checksum_type)
        repo_config = serializer.validated_data.get("repo_config", repository.repo_config)
        compression_type = serializer.validated_data.get(
            "compression_type", repository.compression_type
        )

        if repository.metadata_signing_service:
            signing_service_pk = repository.metadata_signing_service.pk
        else:
            signing_service_pk = None

        kwargs = {
            "repository_version_pk": repository_version.pk,
            "metadata_signing_service": signing_service_pk,
            "checksum_type": checksum_type,
            "repo_config": repo_config,
            "compression_type": compression_type,
        }
        if checkpoint:
            kwargs["checkpoint"] = True
        result = dispatch(
            tasks.publish,
            shared_resources=[repository_version.repository],
            kwargs=kwargs,
        )
        return OperationPostponedResponse(result, request)


class RpmDistributionViewSet(DistributionViewSet, RolesMixin):
    """
    ViewSet for RPM Distributions.
    """

    endpoint_name = "rpm"
    queryset = RpmDistribution.objects.all()
    serializer_class = RpmDistributionSerializer
    queryset_filtering_required_permission = "rpm.view_rpmdistribution"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": ["authenticated"],
                "effect": "allow",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.view_rpmdistribution",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_perms:rpm.add_rpmdistribution",
                    "has_publication_param_model_or_domain_or_obj_perms:rpm.view_rpmpublication",
                    "has_repo_or_repo_ver_param_model_or_domain_or_obj_perms:"
                    "rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.change_rpmdistribution",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmdistribution",
                    "has_publication_param_model_or_domain_or_obj_perms:rpm.view_rpmpublication",
                    "has_repo_or_repo_ver_param_model_or_domain_or_obj_perms:"
                    "rpm.view_rpmrepository",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:rpm.delete_rpmdistribution",
                    "has_model_or_domain_or_obj_perms:rpm.view_rpmdistribution",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:rpm.manage_roles_rpmdistribution",
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "rpm.rpmdistribution_owner"},
            }
        ],
    }

    LOCKED_ROLES = {
        "rpm.rpmdistribution_owner": [
            "rpm.change_rpmdistribution",
            "rpm.delete_rpmdistribution",
            "rpm.manage_roles_rpmdistribution",
            "rpm.view_rpmdistribution",
        ],
        "rpm.rpmdistribution_creator": [
            "rpm.add_rpmdistribution",
        ],
        "rpm.rpmdistribution_viewer": [
            "rpm.view_rpmdistribution",
        ],
    }


class CopyViewSet(viewsets.ViewSet):
    """
    ViewSet for Content Copy.
    """

    serializer_class = CopySerializer

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["create"],
                "principal": ["authenticated"],
                "effect": "allow",
                "condition": [
                    "has_perms_to_copy",
                ],
            },
        ],
    }

    @extend_schema(
        description="Trigger an asynchronous task to copy RPM content"
        "from one repository into another, creating a new"
        "repository version.",
        summary="Copy content",
        operation_id="copy_content",
        request=CopySerializer,
        responses={202: AsyncOperationResponseSerializer},
    )
    def create(self, request):
        """Copy content."""
        serializer = CopySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        dependency_solving = serializer.validated_data["dependency_solving"]
        config = serializer.validated_data["config"]

        config, shared_repos, exclusive_repos = self._process_config(config)

        async_result = dispatch(
            tasks.copy_content,
            shared_resources=shared_repos,
            exclusive_resources=exclusive_repos,
            args=[config, dependency_solving],
            kwargs={},
        )
        return OperationPostponedResponse(async_result, request)

    def _process_config(self, config):
        """
        Change the hrefs into pks within config.

        This method also implicitly validates that the hrefs map to objects and it returns a list of
        repos so that the task can lock on them.
        """
        result = []
        # exclusive use of the destination repos is needed since new repository versions are being
        # created, but source repos can be accessed in a read-only fashion in parallel, so long
        # as there are no simultaneous modifications.
        shared_repos = []
        exclusive_repos = []

        for entry in config:
            r = dict()
            source_version = NamedModelViewSet().get_resource(
                entry["source_repo_version"], RepositoryVersion
            )
            dest_repo = NamedModelViewSet().get_resource(entry["dest_repo"], RpmRepository)
            r["source_repo_version"] = source_version.pk
            r["dest_repo"] = dest_repo.pk
            shared_repos.append(source_version.repository)
            exclusive_repos.append(dest_repo)

            if "dest_base_version" in entry:
                try:
                    r["dest_base_version"] = dest_repo.versions.get(
                        number=entry["dest_base_version"]
                    ).pk
                except RepositoryVersion.DoesNotExist:
                    message = _(
                        "Version {version} does not exist for repository " "'{repo}'."
                    ).format(version=entry["dest_base_version"], repo=dest_repo.name)
                    raise DRFValidationError(detail=message)

            if entry.get("content") is not None:
                r["content"] = []
                for c in entry["content"]:
                    r["content"].append(extract_pk(c))
            result.append(r)

        return result, shared_repos, exclusive_repos
