"""Tests for checkpoint distribution and publications."""

from datetime import datetime, timedelta
import re
from time import sleep
from urllib.parse import urlparse
from aiohttp import ClientResponseError
from tempfile import NamedTemporaryFile
import pytest
import requests
from pulp_rpm.tests.functional.constants import RPM_SIGNED_URL


@pytest.fixture(scope="class")
def rpm_package_factory_class(
    gen_object_with_cleanup,
    pulp_domain_enabled,
    rpm_package_api,
):
    """Return a Package created from uploading an RPM file."""

    def _rpm_package_factory_class(url=RPM_SIGNED_URL, pulp_domain=None):
        with NamedTemporaryFile() as file_to_upload:
            file_to_upload.write(requests.get(url).content)
            file_to_upload.flush()
            upload_attrs = {"file": file_to_upload.name}

            kwargs = {}
            if pulp_domain:
                if not pulp_domain_enabled:
                    raise RuntimeError("Server does not have domains enabled.")
                kwargs["pulp_domain"] = pulp_domain

            return gen_object_with_cleanup(rpm_package_api, **upload_attrs, **kwargs)

    return _rpm_package_factory_class


@pytest.fixture(scope="class")
def setup(
    rpm_repository_factory,
    rpm_publication_factory,
    rpm_distribution_factory,
    rpm_package_factory_class,
    rpm_repository_api,
    monitor_task,
):
    def create_publication(repo, checkpoint):
        artifact = rpm_package_factory_class()
        monitor_task(
            rpm_repository_api.modify(
                repo.pulp_href, {"add_content_units": [artifact.pulp_href]}
            ).task
        )
        return rpm_publication_factory(repository=repo.pulp_href, checkpoint=checkpoint)

    repo = rpm_repository_factory()
    distribution = rpm_distribution_factory(repository=repo.pulp_href, checkpoint=True)

    pubs = []
    # Create publications with 1-second intervals to ensure different timestamps/checkpoint URLs
    pubs.append(create_publication(repo, False))
    sleep(1)
    pubs.append(create_publication(repo, True))
    sleep(1)
    pubs.append(create_publication(repo, False))
    sleep(1)
    pubs.append(create_publication(repo, True))
    sleep(1)
    pubs.append(create_publication(repo, False))

    return pubs, distribution


@pytest.fixture
def checkpoint_url(distribution_base_url):
    def _checkpoint_url(distribution, timestamp):
        distro_base_url = distribution_base_url(distribution.base_url)
        return f"{distro_base_url}{_format_checkpoint_timestamp(timestamp)}/"

    return _checkpoint_url


def _format_checkpoint_timestamp(timestamp):
    return datetime.strftime(timestamp, "%Y%m%dT%H%M%SZ")


class TestCheckpointDistribution:
    @pytest.mark.parallel
    def test_base_path_lists_checkpoints(self, setup, http_get, distribution_base_url):
        pubs, distribution = setup

        response = http_get(distribution_base_url(distribution.base_url)).decode("utf-8")

        checkpoints_ts = set(re.findall(r"\d{8}T\d{6}Z", response))
        assert len(checkpoints_ts) == 2
        assert _format_checkpoint_timestamp(pubs[1].pulp_created) in checkpoints_ts
        assert _format_checkpoint_timestamp(pubs[3].pulp_created) in checkpoints_ts

    @pytest.mark.parallel
    def test_no_trailing_slash_is_redirected(self, setup, http_get, distribution_base_url):
        """Test checkpoint listing when path doesn't end with a slash."""

        pubs, distribution = setup

        response = http_get(distribution_base_url(distribution.base_url[:-1])).decode("utf-8")
        checkpoints_ts = set(re.findall(r"\d{8}T\d{6}Z", response))

        assert len(checkpoints_ts) == 2
        assert _format_checkpoint_timestamp(pubs[1].pulp_created) in checkpoints_ts
        assert _format_checkpoint_timestamp(pubs[3].pulp_created) in checkpoints_ts

    @pytest.mark.parallel
    def test_exact_timestamp_is_served(self, setup, http_get, checkpoint_url):
        pubs, distribution = setup

        pub_1_url = checkpoint_url(distribution, pubs[1].pulp_created)
        response = http_get(pub_1_url).decode("utf-8")

        assert f"<h1>Index of {urlparse(pub_1_url).path}</h1>" in response

    @pytest.mark.parallel
    def test_invalid_timestamp_returns_404(self, setup, http_get, distribution_base_url):
        _, distribution = setup
        with pytest.raises(ClientResponseError) as exc:
            http_get(distribution_base_url(f"{distribution.base_url}invalid_ts/"))

        assert exc.value.status == 404

        with pytest.raises(ClientResponseError) as exc:
            http_get(distribution_base_url(f"{distribution.base_url}20259928T092752Z/"))

        assert exc.value.status == 404

    @pytest.mark.parallel
    def test_non_checkpoint_timestamp_is_redirected(self, setup, http_get, checkpoint_url):
        pubs, distribution = setup
        # Using a non-checkpoint publication timestamp
        pub_3_url = checkpoint_url(distribution, pubs[3].pulp_created)
        pub_4_url = checkpoint_url(distribution, pubs[4].pulp_created)

        response = http_get(pub_4_url).decode("utf-8")
        assert f"<h1>Index of {urlparse(pub_3_url).path}</h1>" in response

        # Test without a trailing slash
        response = http_get(pub_4_url[:-1]).decode("utf-8")
        assert f"<h1>Index of {urlparse(pub_3_url).path}</h1>" in response

    @pytest.mark.parallel
    def test_arbitrary_timestamp_is_redirected(self, setup, http_get, checkpoint_url):
        pubs, distribution = setup
        pub_1_url = checkpoint_url(distribution, pubs[1].pulp_created)
        arbitrary_url = checkpoint_url(distribution, pubs[1].pulp_created + timedelta(seconds=1))

        response = http_get(arbitrary_url).decode("utf-8")
        assert f"<h1>Index of {urlparse(pub_1_url).path}</h1>" in response

        # Test without a trailing slash
        response = http_get(arbitrary_url[:-1]).decode("utf-8")
        assert f"<h1>Index of {urlparse(pub_1_url).path}</h1>" in response

    @pytest.mark.parallel
    def test_current_timestamp_serves_latest_checkpoint(self, setup, http_get, checkpoint_url):
        pubs, distribution = setup
        pub_3_url = checkpoint_url(distribution, pubs[3].pulp_created)
        now_url = checkpoint_url(distribution, datetime.now())

        response = http_get(now_url).decode("utf-8")

        assert f"<h1>Index of {urlparse(pub_3_url).path}</h1>" in response

    @pytest.mark.parallel
    def test_before_first_timestamp_returns_404(self, setup, http_get, checkpoint_url):
        pubs, distribution = setup
        pub_0_url = checkpoint_url(distribution, pubs[0].pulp_created)

        with pytest.raises(ClientResponseError) as exc:
            http_get(pub_0_url).decode("utf-8")

        assert exc.value.status == 404

    @pytest.mark.parallel
    def test_future_timestamp_returns_404(self, setup, http_get, checkpoint_url):
        _, distribution = setup
        url = checkpoint_url(distribution, datetime.now() + timedelta(days=1))

        with pytest.raises(ClientResponseError) as exc:
            http_get(url).decode("utf-8")

        assert exc.value.status == 404
