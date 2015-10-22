#!/usr/bin/env python
import argparse
import hashlib
import json
import lockfile
import os, os.path
import patoolib
import shutil
import stat
import sys

ARCHIVE_FILES   = ['.7z', '.bz2', '.gz', '.rar', '.tar', '.xz', '.zip']
COPY_FILES      = ['.avi', '.flac', '.mkv', '.mp3', '.mp4', '.ogg']
INDEX_NAME      = '.massextract'
LOCKFILE_NAME   = '/tmp/massextract'
HASH_BLOCK_SIZE = 1 << 16 # 64k
VERSION         = '0.2'

# Patoolib has a bug where invoking 7z waits for the user to confirm
# file overwrite. Apply this and any other hotfixes here
# TODO: Remove this whole function once patoolib isn't dumb
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
def extract_archive(fname, out_dir, verbose):
    print 'Extracting', fname, 'to', out_dir
    verbosity = 1 if verbose else -1
    patoolib.extract_archive(fname, outdir=out_dir, verbosity=verbosity)

# Copy file to destination
def copy_file(fname, out_dir, verbose):
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

# Return filename of index for directory
def index_for_dir(directory):
    return os.path.join(directory, INDEX_NAME)

def load_index(directory):
    fname = index_for_dir(directory)
    try:
        f = open(fname, 'r')
        # TODO: Handle error (don't want a partial index) Rebuild?
        try:
            return json.load(f)
        except ValueError as e:
            # Problem interpreting JSON, check if empty file
            st = os.stat(fname)
            if stat.S_ISREG(st.st_mode) and st.st_size == 0:
                print 'WARN: Index %s was empty, ignoring.' % fname
                return {}
            # Bubble any other error back to the top

    except IOError as e:
        if os.errno.ENOENT:
            # Directory hasn't been indexed. Start fresh
            return {}
        # Bubble any other error back to the top

def save_index(directory, idx):
    # Don't pollute with empty files
    if len(idx) > 0:
        fname = index_for_dir(directory)
        with open(fname, 'w') as f:
            return json.dump(idx, f)

# Hash a file. Do it in pieces to reduce memory footprint
def hash_file(file_path):
    sha = hashlib.sha512()
    with open(file_path, 'r') as f:
        while True:
            data = f.read(HASH_BLOCK_SIZE)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()    

# This is the main interface
@lockfile.locked(LOCKFILE_NAME)
def massextract(in_root_dir, out_root_dir, count_threshold, force, verbose):
    dir_cnt = 0
    file_cnt = 0
    pending_cnt = 0
    processed_cnt = 0

    for dir_name, dirs, files in os.walk(in_root_dir):
        rel_dir = os.path.relpath(dir_name, in_root_dir)
        out_dir = os.path.normpath(os.path.join(out_root_dir, rel_dir))
        dir_cnt += 1

	# open index file for rel_dir, used to check file completeness
	idx = load_index(dir_name)

        # Don't bother checking the finger print of unknown extensions
        #for f, t in filter(lambda x: bool, map(classify_file, files)):
        for f, t in filter(None, map(classify_file, files)):
            file_path = os.path.join(dir_name, f)
            f = unicode(f, sys.getfilesystemencoding())
            file_cnt += 1

            try:
                state       = idx[f] # !! FIXME
                # Old sum: to check if file changed, or if we are ready to copy
                old_sum     = state['shasum']
                # The current check count (one more than last time)
                old_cnt     = state['match_cnt'] + 1
                # Has the file been processed?
                processed   = state['processed']
            except KeyError:
                # File not indexed: no sum
                old_sum = ''
                # First iteration
                old_cnt = 0
                # Never been processed
                processed = False

            if force or not processed:
                # File is not known to be stable: calculate new hash
                new_sum = hash_file(file_path)
                if new_sum == old_sum:
                    # Same hash, increment the count
                    new_cnt = old_cnt + 1
                else:
                    # Different hash, reset the count
                    new_cnt = 0

                if new_cnt >= count_threshold and not processed:
                    # File hasn't been processed and is ready: process!
                    processed_cnt += 1

                    # Prepare output directory
                    try:
                        os.makedirs(out_dir)
                    except OSError as e:
                        # Directory already exists is OK. Bubble anything else back up
                        if e.errno == os.errno.EEXIST:
                            pass

                    # Now perform the appropriate copy/extract operation, t, on the file
                    try:
                        t(file_path, out_dir, verbose)
                        processed = True
                    except Exception as e:
                        print 'WARN: could not process %s: %s' % (file_path, e.message)
                else:
                    pending_cnt += 1

                # Update the index based on what we just did
                idx[f] = {'shasum': new_sum, 'match_cnt': new_cnt, 'processed': processed}
        
        # Done with files in directory: rewrite the index
        save_index(dir_name, idx)

    print ''
    print '='*30
    print 'Directories scanned:  %8d' % dir_cnt
    print 'Files scanned:        %8d' % file_cnt
    print 'Files processed:      %8d' % processed_cnt
    print 'Files pending:        %8d' % pending_cnt
    print '='*30

########

if __name__ == '__main__':
    print 'Massextract v%s (c) 2015 Paul Giblock\n' % VERSION

    parser = argparse.ArgumentParser()
    parser.add_argument('indir', help='input directory to scan')
    parser.add_argument('outdir', help='output directory for extraction')
    parser.add_argument('-t', '--threshold', 
            help='number of stable matches needed before extracting',
            type=int,
            default=3)
    parser.add_argument('-f', '--force', action='store_true',
            help='force rescan even for already processed files')
    parser.add_argument('-v', '--verbose', action='store_true',
            help='increase output verbosity')
    args = parser.parse_args()

    hotfix_patoolib()
    massextract(args.indir, args.outdir, args.threshold, args.force, args.verbose)
