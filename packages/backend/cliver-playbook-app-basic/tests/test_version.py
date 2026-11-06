from importlib.metadata import version

from cliver_playbook.app.basic.version import package_version


def test_package_version_reads_the_installed_distribution():
    assert package_version("cliver-playbook-app-basic") == version("cliver-playbook-app-basic")


def test_package_version_falls_back_for_an_uninstalled_distribution():
    assert package_version("cliver-playbook-app-not-installed") == "0.0.0"
