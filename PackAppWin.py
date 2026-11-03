#!/usr/bin/env python3
"""
PackAppWin.py  (rewritten for the unified InstallAssistant.pkg)

Apple now ships macOS installers as a single InstallAssistant.pkg instead of
separate BaseSystem.dmg / InstallESDDmg.pkg / chunklist files. This script
unpacks that .pkg on Windows (pure Python, no 7-Zip needed) and rebuilds the
full "Install macOS ....app" folder, with SharedSupport.dmg placed inside it.

How it works:
  .pkg is a 'xar' archive -> nested packages / 'Payload' files are walked
  -> Payload is pbzx/gzip/xz-compressed cpio -> files are written to disk.
The layout of the .pkg is not assumed; whatever it contains is handled.

Usage:
  python PackAppWin.py                      (looks for InstallAssistant.pkg next to the script)
  python PackAppWin.py path\\to\\InstallAssistant.pkg [output_dir]
"""
import os, sys, struct, zlib, lzma, gzip, bz2, shutil, time
import xml.etree.ElementTree as ET

CHUNK = 4 * 1024 * 1024
IS_WIN = os.name == "nt"
LINE = "-" * 50

# loose files worth keeping from the package root (lowercase name -> output name)
WANTED = {
    "sharedsupport.dmg": "SharedSupport.dmg",
    "basesystem.dmg": "BaseSystem.dmg",
    "basesystem.chunklist": "BaseSystem.chunklist",
    "applediagnostics.dmg": "AppleDiagnostics.dmg",
    "applediagnostics.chunklist": "AppleDiagnostics.chunklist",
    "installesddmg.pkg": "InstallESD.dmg",
    "installinfo.plist": "InstallInfo.plist",
}


# ---------------------------------------------------------------- helpers
def title(s):
    print(LINE)
    print("{:^50}".format(s))
    print(LINE)


def pause():
    if IS_WIN:
        os.system("pause")


def die(msg):
    print("\nError: " + msg)
    pause()
    sys.exit(1)


def lp(path):
    """Long-path-safe absolute path on Windows (macOS apps have deep trees)."""
    path = os.path.abspath(path)
    if IS_WIN and not path.startswith("\\\\?\\"):
        if path.startswith("\\\\"):
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path
    return path


def safe_parts(name):
    """Turn an archive path into safe path components for the local FS."""
    out = []
    for p in name.replace("\\", "/").split("/"):
        if p in ("", ".", ".."):
            continue
        if IS_WIN:
            for ch in '<>:"|?*':
                p = p.replace(ch, "_")
            p = p.rstrip(" .") or "_"
        out.append(p)
    return out


def progress(done, total, label):
    pct = 100 if total == 0 else int(done * 100 / total)
    sys.stdout.write("\r    {:<28.28} {:3d}%".format(label, pct))
    sys.stdout.flush()


# ---------------------------------------------------------------- xar (.pkg)
class Xar:
    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(28)
        if len(hdr) < 28 or hdr[:4] != b"xar!":
            self.f.close()
            raise ValueError("not a xar/pkg file")
        _, hsize, _, clen, _, _ = struct.unpack(">4sHHQQI", hdr)
        self.f.seek(hsize)
        toc = zlib.decompress(self.f.read(clen))
        self.heap = hsize + clen
        self.toc = ET.fromstring(toc).find("toc")

    def close(self):
        self.f.close()

    def entries(self, node=None, prefix=""):
        node = self.toc if node is None else node
        for fe in node.findall("file"):
            name = fe.findtext("name") or ""
            if fe.findtext("type") == "directory":
                yield from self.entries(fe, prefix + name + "/")
            elif fe.find("data") is not None:
                yield prefix + name, fe

    def extract(self, fe, dest, label):
        data = fe.find("data")
        offset = int(data.findtext("offset"))
        length = int(data.findtext("length"))
        enc = data.find("encoding")
        style = enc.get("style", "") if enc is not None else ""
        if "gzip" in style:
            dec = zlib.decompressobj(zlib.MAX_WBITS | 32)
        elif "bzip2" in style:
            dec = bz2.BZ2Decompressor()
        elif "lzma" in style or "xz" in style:
            dec = lzma.LZMADecompressor()
        else:
            dec = None
        self.f.seek(self.heap + offset)
        left = length
        with open(lp(dest), "wb") as out:
            while left > 0:
                buf = self.f.read(min(CHUNK, left))
                if not buf:
                    raise IOError("package is truncated (incomplete download?)")
                left -= len(buf)
                out.write(dec.decompress(buf) if dec else buf)
                progress(length - left, length, label)
        print()


# ---------------------------------------------------------------- payload -> cpio
def _read_chunks(f):
    while True:
        b = f.read(CHUNK)
        if not b:
            return
        yield b


def payload_stream(path):
    """Yield the decompressed cpio bytes of a Payload file."""
    f = open(path, "rb")
    magic = f.read(6)
    f.seek(0)
    if magic[:4] == b"pbzx":
        f.read(12)  # magic + max-chunk-size
        while True:
            h = f.read(16)
            if len(h) < 16:
                break
            _, csize = struct.unpack(">QQ", h)
            data = f.read(csize)
            if data[:6] == b"\xfd7zXZ\x00":
                data = lzma.decompress(data)
            yield data
    elif magic[:2] == b"\x1f\x8b":
        f.close()
        with gzip.open(path, "rb") as g:
            yield from _read_chunks(g)
        return
    elif magic[:6] == b"\xfd7zXZ\x00":
        f.close()
        with lzma.open(path, "rb") as g:
            yield from _read_chunks(g)
        return
    elif magic[:3] == b"BZh":
        f.close()
        with bz2.open(path, "rb") as g:
            yield from _read_chunks(g)
        return
    else:
        yield from _read_chunks(f)
    f.close()


class Stream:
    def __init__(self, gen):
        self.gen, self.buf = gen, bytearray()

    def read(self, n):
        while len(self.buf) < n:
            try:
                self.buf += next(self.gen)
            except StopIteration:
                break
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def skip(self, n):
        while n > 0:
            n -= len(self.read(min(n, CHUNK)))
            if not self.buf and n > 0:
                try:
                    self.buf += next(self.gen)
                except StopIteration:
                    return


def extract_cpio(stream, outdir, symlinks):
    count = 0
    while True:
        magic = stream.read(6)
        if len(magic) < 6:
            break
        if magic == b"070707":  # odc (used by macOS pkgs)
            h = stream.read(70)
            mode = int(h[12:18], 8)
            nsize = int(h[53:59], 8)
            fsize = int(h[59:70], 8)
            name = stream.read(nsize)
            npad = dpad = 0
        elif magic == b"070701" or magic == b"070702":  # newc
            h = stream.read(104)
            v = [int(h[i:i + 8], 16) for i in range(0, 104, 8)]
            mode, fsize, nsize = v[1], v[6], v[11]
            name = stream.read(nsize)
            stream.read((4 - (110 + nsize) % 4) % 4)
            dpad = (4 - fsize % 4) % 4
        else:
            raise ValueError("unrecognised cpio data (bad Payload?)")
        name = name.rstrip(b"\0").decode("utf-8", "replace")
        if name == "TRAILER!!!":
            break
        parts = safe_parts(name)
        kind = mode & 0o170000
        dest = os.path.join(outdir, *parts) if parts else None
        if dest is None:
            stream.skip(fsize + dpad)
            continue
        if kind == 0o040000:
            os.makedirs(lp(dest), exist_ok=True)
        elif kind == 0o120000:  # symlink: Windows can't store these reliably
            target = stream.read(fsize).decode("utf-8", "replace")
            symlinks.append("{} -> {}".format("/".join(parts), target))
            stream.read(dpad)
            continue
        elif kind == 0o100000:
            os.makedirs(lp(os.path.dirname(dest)), exist_ok=True)
            left = fsize
            with open(lp(dest), "wb") as out:
                while left > 0:
                    b = stream.read(min(CHUNK, left))
                    if not b:
                        raise IOError("Payload ended early")
                    out.write(b)
                    left -= len(b)
            count += 1
            if count % 500 == 0:
                sys.stdout.write("\r    {} files written...".format(count))
                sys.stdout.flush()
        else:
            stream.skip(fsize)
        stream.read(dpad)
    print("\r    {} files written.      ".format(count))
    return count


# ---------------------------------------------------------------- driver
def process_pkg(pkg, outdir, tmpdir, symlinks, depth=0):
    x = Xar(pkg)
    try:
        for rel, fe in list(x.entries()):
            base = rel.rsplit("/", 1)[-1]
            low = base.lower()
            tmp = os.path.join(tmpdir, "w{}_{}".format(depth, abs(hash(rel))))
            if base == "Payload":
                x.extract(fe, tmp, "Payload")
                print("    Expanding Payload...")
                extract_cpio(Stream(payload_stream(tmp)), os.path.join(outdir, "payload"), symlinks)
                os.remove(lp(tmp))
            elif low in WANTED:
                # Could be a real file or (rarely) a nested xar; keep real files as-is
                x.extract(fe, os.path.join(outdir, WANTED[low]), WANTED[low])
            elif low.endswith(".pkg"):
                x.extract(fe, tmp, base)
                try:
                    print("  Opening nested package {}".format(base))
                    process_pkg(tmp, outdir, tmpdir, symlinks, depth + 1)
                except ValueError:
                    pass  # not a xar; ignore
                os.remove(lp(tmp))
    finally:
        x.close()


def assemble(outdir):
    """Move everything into a proper Install macOS app layout."""
    payload = os.path.join(outdir, "payload")
    app = None
    apps_dir = os.path.join(payload, "Applications")
    if os.path.isdir(apps_dir):
        for n in os.listdir(apps_dir):
            if n.endswith(".app"):
                app = os.path.join(apps_dir, n)
                break
    if app is None:
        return None
    final = os.path.join(outdir, os.path.basename(app))
    if os.path.exists(final):
        shutil.rmtree(lp(final))
    os.rename(lp(app), lp(final))
    shutil.rmtree(lp(payload), ignore_errors=True)
    ss_dir = os.path.join(final, "Contents", "SharedSupport")
    os.makedirs(lp(ss_dir), exist_ok=True)
    for key in ("SharedSupport.dmg", "InstallInfo.plist"):
        src = os.path.join(outdir, key)
        if os.path.isfile(lp(src)):
            os.replace(lp(src), lp(os.path.join(ss_dir, key)))
    return final


def run(pkg, outdir):
    clear_title = "Unpacking InstallAssistant.pkg"
    title(clear_title)
    size = os.path.getsize(pkg)
    os.makedirs(outdir, exist_ok=True)
    free = shutil.disk_usage(outdir).free
    print("Package : {}  ({:.1f} GB)".format(pkg, size / 1e9))
    print("Output  : {}  ({:.1f} GB free)".format(outdir, free / 1e9))
    if free < size * 1.3:
        ans = input("Free space looks low (need ~1.3x the .pkg size). Continue? [y/N] ")
        if ans.strip().lower() != "y":
            return
    tmpdir = os.path.join(outdir, "_tmp")
    os.makedirs(tmpdir, exist_ok=True)
    symlinks = []
    t0 = time.time()
    try:
        process_pkg(pkg, outdir, tmpdir, symlinks)
    except (ValueError, IOError, zlib.error, lzma.LZMAError) as e:
        shutil.rmtree(lp(tmpdir), ignore_errors=True)
        die("{}\nThe file may be corrupt or not an InstallAssistant.pkg.".format(e))
    shutil.rmtree(lp(tmpdir), ignore_errors=True)
    app = assemble(outdir)
    if symlinks:
        with open(lp(os.path.join(outdir, "symlinks.txt")), "w", encoding="utf-8") as f:
            f.write("\n".join(symlinks))
    print()
    title("Done in {:.0f}s".format(time.time() - t0))
    if app:
        print("Installer app : {}".format(app))
        print("SharedSupport : {}".format(os.path.join(app, "Contents", "SharedSupport")))
        print("\nNote: Windows does not keep Unix permissions or symlinks.")
        print("If you copy this app to a Mac, run once:")
        print('  chmod +x "<app>/Contents/Resources/createinstallmedia"')
        if symlinks:
            print("({} symlinks were skipped; listed in symlinks.txt)".format(len(symlinks)))
    else:
        print("No 'Install macOS' app payload found; loose files are in:")
        print("  " + outdir)


def main():
    here = os.path.dirname(os.path.realpath(__file__))
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    pkg = args[0] if args else os.path.join(here, "InstallAssistant.pkg")
    if not os.path.isfile(pkg):
        title("InstallAssistant.pkg not found")
        pkg = input("Drag the .pkg here (or type its path): ").strip().strip('"')
        if not os.path.isfile(pkg):
            die("File not found: " + pkg)
    outdir = args[1] if len(args) > 1 else os.path.join(here, "InstallerOutput")
    run(os.path.abspath(pkg), os.path.abspath(outdir))
    pause()


if __name__ == "__main__":
    main()
