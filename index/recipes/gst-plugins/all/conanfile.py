import glob
import os
import re

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.build import cross_building
from conan.tools.files import copy, get, load, rm, rmdir, save
from conan.tools.gnu import PkgConfigDeps
from conan.tools.layout import basic_layout
from conan.tools.meson import Meson, MesonToolchain

required_conan_version = ">=2.4"

MODULES = ("gstreamer", "gst-plugins-base", "gst-plugins-good", "gst-plugins-bad")

# fmt: off
# Plugins built without any optional dependency. Everything else is off: the build
# runs with auto_features=disabled, so nothing turns on because a library happens
# to be installed on the build machine. To add a plugin, add its meson option here
# (and its dependency to requirements(), if it has one).
PLUGINS = {
    "gstreamer": ("coretracers",),
    "gst-plugins-base": (
        "app", "audioconvert", "audiomixer", "audiorate", "audioresample",
        "audiotestsrc", "compositor", "encoding", "gio", "overlaycomposition",
        "pbtypes", "playback", "rawparse", "subparse", "tcp", "typefind",
        "videoconvertscale", "videorate", "videotestsrc", "volume",
    ),
    "gst-plugins-good": (
        "audioparsers", "autodetect", "avi", "debugutils", "deinterlace", "flv",
        "imagefreeze", "interleave", "isomp4", "matroska", "multifile", "multipart",
        "rtp", "rtpmanager", "rtsp", "udp", "videobox", "videocrop", "videofilter",
        "wavparse", "y4m",
    ),
    "gst-plugins-bad": (
        "autoconvert", "codectimestamper", "debugutils", "jpegformat",
        "mpegtsdemux", "mpegtsmux", "rtp", "sdp", "shm", "switchbin", "timecode",
        "unixfd", "videofilters", "videoparsers",
    ),
}

# System libraries taken from the build machine (native) or the sysroot (cross),
# as pkg-config modules. pkg-config sees these, what they require, and Conan's
# packages: nothing else. (Some plugins pick up optional libraries without asking,
# e.g. timecode links libltc whenever pkg-config can find it.)
SYSTEM_PC = {
    "with_x11": ("x11", "x11-xcb", "xext"),
    "with_gl": ("egl", "gl", "glesv2", "glx", "opengl"),
}
# fmt: on


def pc_requires(value):
    """'a >= 1.0, b' -> ['a', 'b']"""
    return re.sub(r"[<>=!]+\s*\S+", " ", value).replace(",", " ").split()


class GstPluginsConan(ConanFile):
    """GStreamer core + gst-plugins-base/good/bad in one package, one version.

    The four official release tarballs are unpacked as Meson subprojects of a
    two-line parent project, the same way the GStreamer monorepo builds them: one
    configure, one ninja run, and the modules always match each other.

    System libraries (not Conan packages, never packaged here):
    - with_x11: libX11, libX11-xcb, libxcb, libXext (ximagesink, GL on X11/GLX).
    - with_gl: libglvnd/mesa EGL + GL + GLES headers and libraries.
    They come from the build machine for a native build, and from the sysroot
    (tools.build:sysroot) for a cross build. The target must provide them at runtime.

    with_nvcodec builds nvh264enc/nvh265enc/nvh264dec/..., cudaupload etc. It needs
    no CUDA SDK at build time: libcuda and libnvidia-encode are loaded at runtime,
    and the elements only register when the driver provides them. With with_gl, the
    CUDA library gets GL interop, which links the GL (and X11) libraries.
    """

    name = "gst-plugins"
    description = "GStreamer core with gst-plugins-base, -good and -bad"
    license = "LGPL-2.1-or-later"
    homepage = "https://gstreamer.freedesktop.org"
    url = "https://github.com/Awareness10/conan_config"
    topics = ("gstreamer", "multimedia", "video", "audio", "streaming")
    # Plugins are always shared modules, and GLib's type system needs one shared GLib.
    package_type = "shared-library"
    settings = "os", "arch", "compiler", "build_type"
    options = {  # noqa: RUF012 - Conan reads these class attributes
        "with_x11": [True, False],
        "with_gl": [True, False],
        "with_nvcodec": [True, False],
        "with_v4l2": [True, False],
    }
    default_options = {  # noqa: RUF012
        "with_x11": True,
        "with_gl": True,
        "with_nvcodec": True,
        "with_v4l2": True,
        "glib/*:shared": True,
    }

    def layout(self):
        basic_layout(self, src_folder="src")

    def requirements(self):
        self.requires("glib/[>=2.76 <3]", transitive_headers=True)
        self.requires("zlib/[>=1.2.11 <2]")

    def build_requirements(self):
        self.tool_requires("meson/[>=1.4 <2]")
        self.tool_requires("pkgconf/[>=2.1 <4]")
        self.tool_requires("flex/2.6.4")  # gst-launch pipeline parser
        self.tool_requires("bison/[>=3.7 <4]")
        self.tool_requires("glib/<host_version>")  # glib-mkenums, glib-genmarshal

    def validate(self):
        if self.settings.os != "Linux":
            raise ConanInvalidConfiguration(f"{self.ref} is only set up for Linux")
        if not self.dependencies["glib"].options.shared:
            raise ConanInvalidConfiguration(f"{self.ref} needs glib/*:shared=True")

    def source(self):
        for module, src in self.conan_data["sources"][self.version].items():
            dst = os.path.join(self.source_folder, "subprojects", module)
            get(self, **src, strip_root=True, destination=dst)
        modules = ", ".join(f"'{m}'" for m in MODULES)
        save(
            self,
            os.path.join(self.source_folder, "meson.build"),
            f"project('gst-plugins', 'c', version: '{self.version}')\n"
            f"foreach module : [{modules}]\n  subproject(module)\nendforeach\n",
        )

    @property
    def _meson_options(self):
        opts = {m: dict.fromkeys(PLUGINS[m], "enabled") for m in MODULES}
        opts["gstreamer"]["tools"] = "enabled"
        # libgstcheck; good/bad's docs/meson.build also fail without it, even with
        # docs off (core only defines plugins_cache_generator when check is on).
        opts["gstreamer"]["check"] = "enabled"
        opts["gst-plugins-base"]["tools"] = "enabled"
        if self.options.with_x11:
            opts["gst-plugins-base"].update(x11="enabled", xshm="enabled")
        if self.options.with_gl:
            x11 = bool(self.options.with_x11)
            opts["gst-plugins-base"].update(
                gl="enabled",
                gl_api=["opengl", "gles2"],
                gl_platform=["glx", "egl"] if x11 else ["egl"],
                gl_winsys=(["x11"] if x11 else []) + ["egl", "surfaceless"],
            )
            opts["gst-plugins-bad"]["gl"] = "enabled"  # also CUDA <-> GL interop
        if self.options.with_v4l2:
            opts["gst-plugins-good"]["v4l2"] = "enabled"
        if self.options.with_nvcodec:
            # cuda-nvmm stays disabled: upstream turns it on when Jetson Multimedia
            # API or DeepStream headers are installed on the build machine, and on
            # Tegra that also compiles out the NVENC/NVDEC elements.
            opts["gst-plugins-bad"]["nvcodec"] = "enabled"
        return opts

    def generate(self):
        PkgConfigDeps(self).generate()
        tc = MesonToolchain(self)
        tc.project_options["auto_features"] = "disabled"
        tc.project_options["pkgconfig.relocatable"] = True
        for module, opts in self._meson_options.items():
            tc.subproject_options[module] = [opts]
        # pkg-config searches only the generators folder: Conan's .pc files plus
        # the allowed system ones copied there.
        tc.properties["pkg_config_libdir"] = [self.generators_folder]
        self._copy_system_pc_files(tc)
        tc.generate()

    def _copy_system_pc_files(self, tc):
        """Copy the SYSTEM_PC modules (and what they require) next to Conan's.

        Conan's .pc files take precedence. A cross build copies the sysroot's files,
        with absolute paths moved into the sysroot. PKG_CONFIG_SYSROOT_DIR can't do
        that: pkgconf would put the sysroot in front of Conan's package paths too.
        """
        wanted = [
            m for opt, ms in SYSTEM_PC.items() if self.options.get_safe(opt) for m in ms
        ]
        if not wanted:
            return
        cross = cross_building(self)
        root = self.conf.get("tools.build:sysroot", check_type=str) if cross else "/"
        if not root:
            raise ConanException(
                "Cross-building with_x11/with_gl takes X11/GL from the target's "
                "sysroot: set tools.build:sysroot, or disable the options"
            )
        multiarch = sorted(glob.glob(os.path.join(root, "usr", "lib", "*-linux-gnu*")))
        pc_dirs = [os.path.join(d, "pkgconfig") for d in multiarch] + [
            os.path.join(root, "usr", sub, "pkgconfig")
            for sub in ("lib64", "lib", "share")
        ]
        system = {}
        for pc in (
            pc for d in pc_dirs for pc in sorted(glob.glob(os.path.join(d, "*.pc")))
        ):
            system.setdefault(os.path.basename(pc)[:-3], pc)

        while wanted:
            name = wanted.pop()
            dst = os.path.join(self.generators_folder, f"{name}.pc")
            if name not in system or os.path.exists(dst):
                continue  # Conan's own, already copied, or missing (meson reports it)
            text = load(self, system[name])
            if cross:
                text = re.sub(r"^(\w+)=/", rf"\1={root}/", text, flags=re.MULTILINE)
            save(self, dst, text)
            for line in text.splitlines():
                key, _, value = line.partition(":")
                if key in ("Requires", "Requires.private"):
                    wanted += pc_requires(value)

        if cross:
            # libX11.so needs libxcb.so etc.: let ld find them when linking programs.
            for d in multiarch + [d.replace("/usr/lib/", "/lib/") for d in multiarch]:
                tc.extra_ldflags.append(f"-Wl,-rpath-link,{d}")

    def build(self):
        meson = Meson(self)
        meson.configure()
        meson.build()

    def package(self):
        for module in MODULES:
            src = os.path.join(self.source_folder, "subprojects", module)
            copy(
                self,
                "COPYING*",
                src,
                os.path.join(self.package_folder, "licenses", module),
            )
        Meson(self).install()
        # Conan generates the CMake/pkg-config files; man pages, m4 and gdb helpers
        # aren't needed. (share/gstreamer-1.0 keeps presets and encoding profiles.)
        for sub in ("cmake", "man", "aclocal", "gdb", "bash-completion"):
            rmdir(self, os.path.join(self.package_folder, "share", sub))
        rmdir(self, os.path.join(self.package_folder, "share", "gstreamer-1.0", "gdb"))
        # Documentation helpers (Conan installs libexec into bin).
        for helper in (
            "gst-hotdoc-plugins-scanner",
            "gst-plugins-doc-cache-generator",
            "gst-completion-helper",
        ):
            rm(self, helper, os.path.join(self.package_folder, "bin", "gstreamer-1.0"))

    def _gst_pkg_config_modules(self):
        """{name: (libs, includedirs, requires)} from the installed .pc files.

        The components follow the libraries the options actually built, so there is
        no hand-written list to keep in sync with each GStreamer release.
        """
        pcdir = os.path.join(self.package_folder, "lib", "pkgconfig")
        modules = {}
        for path in sorted(glob.glob(os.path.join(pcdir, "*.pc"))):
            variables, fields = {"pcfiledir": pcdir}, {}
            for line in load(self, path).splitlines():
                if m := re.match(r"([\w.]+)\s*([=:])\s*(.*)", line):
                    key, sep, value = m.groups()
                    value = re.sub(
                        r"\$\{(\w+)\}", lambda v, e=variables: e.get(v[1], ""), value
                    )
                    (variables if sep == "=" else fields)[key] = value
            flags = fields.get("Cflags", "").split() + fields.get("Libs", "").split()
            includedirs = [
                os.path.relpath(os.path.normpath(f[2:]), self.package_folder)
                for f in flags
                if f.startswith("-I")
            ]
            libs = [f[2:] for f in flags if f.startswith("-l")]
            requires = pc_requires(fields.get("Requires", ""))
            modules[os.path.basename(path)[:-3]] = (libs, includedirs, requires)
        return modules

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "GStreamer")
        self.cpp_info.set_property("cmake_target_name", "GStreamer::GStreamer")

        conan_pc = {  # pkg-config name -> Conan component, e.g. gobject-2.0 -> glib::gobject-2.0
            comp.get_property("pkg_config_name") or name: f"{dep.ref.name}::{name}"
            for dep in self.dependencies.host.values()
            for name, comp in dep.cpp_info.components.items()
        }
        libdir = os.path.join(self.package_folder, "lib")
        gst = self._gst_pkg_config_modules()
        for name, (libs, includedirs, requires) in gst.items():
            short = name.removesuffix("-1.0")
            short = short.removeprefix("gstreamer-") if short != "gstreamer" else short
            comp = self.cpp_info.components[name]
            comp.set_property("pkg_config_name", name)
            comp.set_property("cmake_target_name", f"GStreamer::{short}")
            comp.includedirs = includedirs
            ours = [
                lib
                for lib in libs
                if os.path.exists(os.path.join(libdir, f"lib{lib}.so"))
            ]
            comp.libs = ours
            comp.system_libs = [lib for lib in libs if lib not in ours]  # m, atomic
            # Other requirements (x11-xcb, egl, ...) are system libraries.
            comp.requires = [
                r if r in gst else conan_pc[r]
                for r in requires
                if r in gst or r in conan_pc
            ]

        # The plugin modules, loaded at runtime from lib/gstreamer-1.0.
        plugins = self.cpp_info.components["plugins"]
        plugins.set_property("cmake_target_name", "GStreamer::plugins")
        plugins.requires = ["gstreamer-1.0", "zlib::zlib"]
        plugins.libdirs = []
        plugins.includedirs = []

        # Use this package's plugins and scanner, not the system GStreamer's. Add
        # other plugin folders (e.g. L4T's NVIDIA plugins) with GST_PLUGIN_PATH_1_0.
        self.runenv_info.define_path(
            "GST_PLUGIN_SYSTEM_PATH_1_0", os.path.join(libdir, "gstreamer-1.0")
        )
        self.runenv_info.define_path(
            "GST_PLUGIN_SCANNER_1_0",
            os.path.join(
                self.package_folder, "bin", "gstreamer-1.0", "gst-plugin-scanner"
            ),
        )
