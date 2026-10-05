from conan.api.output import ConanOutput
from conan.cli.command import conan_command


@conan_command(group="Custom")
def hello(conan_api, parser, *args):
    """
    Example custom command installed from the conan_config repo.
    """
    parser.add_argument("name", nargs="?", default="world", help="Who to greet")
    args = parser.parse_args(*args)
    ConanOutput().info(f"Hello, {args.name}! (CONAN_HOME={conan_api.home_folder})")
