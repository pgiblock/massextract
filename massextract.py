#!/usr/bin/env python
import argparse
import lockfile
import os, os.path
import patoolib
import shutil

ARCHIVE_FILES = ['.7z', '.bz2', '.gz', '.rar', '.tar', '.xz', '.zip']
COPY_FILES    = ['.avi', '.flac', '.mkv', '.mp3', '.mp4', '.ogg']

in_root_dir  = '/Users/pgiblock'
out_root_dir = '/Users/pgiblock/out'

# Patoolib has a bug where invoking 7z waits for the user to confirm
# file overwrite. Apply this and any other hotfixes here
def hotfix_patoolib():
    import patoolib.programs.p7zip as p7zip
    import patoolib.programs.unrar as unrar
    
    def extract_7z_singlefile(archive, compression, cmd, verbosity, outdir):
        return [cmd, 'e', '-y', '-o%s' % outdir, '--', archive]

    def extract_7z(archive, compression, cmd, verbosity, outdir):
        return [cmd, 'x', '-y', '-o%s' % outdir, '--', archive]

    def extract_rar (archive, compression, cmd, verbosity, outdir):
        return ([cmd, 'x', '-y', '--', os.path.abspath(archive)], {'cwd': outdir})

    for i in ['bzip2', 'gzip', 'compress', 'xz', 'lzma', '7z_singlefile']:
        setattr(p7zip, 'extract_'+i, extract_7z_singlefile)

    for i in ['zip', 'rar', 'cab', 'arj', 'cpio', 'rpm', 'deb', 'iso', '7z']:
        setattr(p7zip, 'extract_'+i, extract_7z)

    unrar.extract_rar = extract_rar    

# Extract file to destination
def extract_archive(fname, out_dir):
    print 'Extracting', fname, 'to', out_dir
    patoolib.extract_archive(fname, outdir=out_dir, verbosity=1)

# Copy file to destination
def copy_file(fname, out_dir):
    print 'Copying', fname, 'to', out_dir
    shutil.copy(fname, out_dir)

# We will just match on extensions for now. Although checking the mimetype
# might be considered more correct, there are many formats stored as gzip,
# zip, or even flac, that we do not want to actually extract. We will only
# consider files given a typical internet naming convention.
def classify_file(fname):
    root, ext = os.path.splitext(fname)
    if ext in ARCHIVE_FILES:
        return (fname, extract_archive)
    elif ext in COPY_FILES:
        return (fname, copy_file)
    else:
        return None

# This is the main interface
@lockfile.locked('/tmp/massextract')
def massextract():
    for dir_name, dirs, files in os.walk(in_root_dir):
        rel_dir = os.path.relpath(dir_name, in_root_dir)
        out_dir = os.path.normpath(os.path.join(out_root_dir, rel_dir))

        # Don't bother checking the finger print of unknown extensions
        #for f, t in filter(lambda x: bool, map(classify_file, files)):
        for f, t in filter(None, map(classify_file, files)):
            file_path = os.path.join(dir_name, f)

            # Got a matching extension, preemptively create output dir
            try:
                os.makedirs(out_dir)
            except OSError as e:
                # Directory already exists is OK. Bubble anything else back up
                if e.errno == os.errno.EEXIST:
                    pass

            # Now perform the appropriate copy/extract operation, t, on the file
            try:
                t(file_path, out_dir)
            except Exception as e:
                print 'WARN: could not process %s: %s' % (file_path, e.message)

if __name__ == '__main__':
    hotfix_patoolib()
    massextract()
