#!/bin/bash
archive=$1
new_basename=$2
target_dir=$3

cleanup() {
  popd
  if [[ -d "$work_dir" ]]; then
    echo "Cleaning up work dir..."
    rm -rf "$work_dir"
  fi
}

if [[ ! -f "$archive" ]]; then
  echo "File not found: $archive"
  exit 1
fi

if [[ "$archive" == *.7z ]]; then
  archive_ext=".7z"
elif [[ "$archive" == *.zip ]]; then
  archive_ext=".zip"
else
  echo "Archive extension not supported."
  exit 1
fi

if [[ ! -n "$target_dir" ]]; then
  echo "Target directory not specified; using cwd"
  target_dir="`pwd`"
fi

if [[ ! -d "$target_dir" ]]; then
  echo "Target directory does not exist."
  exit 1
fi

new_filename="$target_dir"/"$new_basename""$archive_ext"
if [[ -f "$new_filename" ]]; then
  echo "Target archive $new_filename already exists!"
  exit 1
fi
if [[ ! -w "$target_dir" ]]; then
  echo "Target destination is unwritable: $new_filename"
  exit 1
fi

old_basename=`basename -s "$archive_ext" "$archive"`
echo "Old archive: $archive"
echo "New archive: $new_basename$archive_ext"

work_dir=`mktemp -d -p .`
pushd "$work_dir"

if [[ $archive_ext == ".7z" ]]; then
  7za x ../"$archive"
else
  unzip ../"$archive"
fi
ret=$?
if [[ $ret -ne 0 ]]; then
  echo "Unarchiving returned $ret error code. Stopping."
  cleanup
  exit 1
fi

if [[ -f "$old_basename".cue ]]; then
  echo "Found cuesheet. Editing..."
  sed -i "s/$old_basename/$new_basename/g" "$old_basename".cue
fi

# Simplest way to escape parentheses and slashes for use in rename/sed
old_basename_e=`printf '%q' "$old_basename"`
new_basename_e=`printf '%q' "$new_basename"`

rename -v "s/$old_basename_e/$new_basename_e/" *

if [[ $archive_ext == ".7z" ]]; then
  t7z a "$new_filename" *
else
  zip -0 -D "$new_filename" *
  trrntzip "$new_filename"
fi
ret=$?
if [[ $ret -ne 0 ]]; then
  echo "Packing returned $ret error code. Stopping."
  cleanup
  exit 1
fi
cleanup
