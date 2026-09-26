"""Example hook: warn when a recipe does not declare a license."""


def pre_export(conanfile):
    if not getattr(conanfile, "license", None):
        conanfile.output.warning(
            f"[hook_check_license] {conanfile.name}: recipe has no 'license' attribute"
        )
