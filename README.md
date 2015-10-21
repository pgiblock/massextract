# Installing

You don't have to install massextract, but you will need some dependencies:

  - `pip install lockfile`
  - `pip install patool`

# Running  

Run `./massextract.py --help` for usage information.

If you want to extract and are not concerned with the integrity of files (say,
a media file is not finished downloading) then you can set the threshold to 0.
This will cause massextract to attempt all recognized files.  You can later
force re-evaluation of these files by passing the `-f,--force` flag.
