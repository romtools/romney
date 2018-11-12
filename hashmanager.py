import os
import glob
import math
import time
import sqlite3
import binascii
import hashlib, zlib
from multiprocessing import Pool

class HashManager:
  def __init__(self, db_path, threads=4):
    self.threads = threads
    self.db_path = db_path

    if not next(self._sql("select count(1) from sqlite_master where type='table' and name='files'"))[0]:
      self.log("Database is blank. Populating tables")
      self._sql('create table files (samplesum text, sha1sum text, crc32 text, filesize integer, updated integer, modtime real)')

  def _sql(self, *args):
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    ret = conn.execute(*args)
    conn.commit()
    return ret

  def log(self, *args):
    print("[HashManager]", *args)

  # Cache file checksums by samplesum+modtime+filesize, an impenetrable genius trio. Samplesum occasionally has collisions, but those
  # scenarios should be covered by modtime. (It's likely that modtime+filesize is enough)
  def cache_insert_file(self, samplesum, sha1, crc32, filesize, modtime):
    existing_file = self.cache_get_file(samplesum, filesize, modtime)
    if existing_file:
      if existing_file['sha1sum'] != sha1 or existing_file['crc32'] != crc32:
        self.log("ERROR: While inserting checksum data into DB, file already existed and one or more checksums differ! Deleting old row and replacing.")
        self._sql('delete from files where samplesum=?', (samplesum,))
      else:
        return True
    self._sql('insert into files(samplesum, sha1sum, crc32, filesize, updated, modtime) values (?, ?, ?, ?, ?, ?)', (samplesum, sha1, crc32, filesize, math.floor(time.time()), modtime))
    self.log("Inserting cached checksum")

  def cache_get_file(self, samplesum, filesize, modtime):
    try:
      row = next(self._sql('select * from files where samplesum=? and filesize=? and modtime=?', (samplesum, filesize, modtime)))
      return {'sha1' : row['sha1sum'], 'crc32' : row['crc32']}
    except StopIteration:
      return False

  def get_crc(self, path):
    return self.get_sums(path)['crc32']

  def get_sha1(self, path):
    return self.get_sums(path)['sha1']

  def get_samplesum(self, path):
    return self.samplesum(path)

  def get_sums(self, path):
    if os.path.isdir(path):
      raise Exception('Path provided is a directory; expected file')

    samplesum = self.samplesum(path)
    size = os.path.getsize(path)
    mtime = os.path.getmtime(path)
    cache = self.cache_get_file(samplesum, size, mtime)
    if cache:
      return cache
    sums = self.calculate_sums(path)
    self.cache_insert_file(samplesum, sums['sha1'], sums['crc32'], size, mtime)
    return sums

  def multiget_sums(self, root_or_list):

    if isinstance(root_or_list, str):
      files = list(glob.iglob(root_or_list + '/**/*', recursive=True))
    elif isinstance(root_or_list, list):
      files = root_or_list
    else:
      raise Exception('Expected path to a root folder, or a list of paths')

    self.log('Multiget sums: ', files)

    # Strip directories
    files = [f for f in files if not os.path.isdir(f)]

    sums = {}

    # Multiget samplesums first (multiprocessing boost)
    samplesums = self.samplesum(files)

    # Populate via cache first
    self.log("Populating via cache first...")
    to_sum = []
    for path in files:
      cache = self.cache_get_file(samplesums[path], os.path.getsize(path), os.path.getmtime(path))
      if cache:
        self.log("Got cache entry for file %s" % path)
        sums[path] = cache
        continue
      to_sum.append(path)

    # Any uncached files now have checksums calculated in parallel
    if to_sum:
      print("Sending remaining files to checksum engine...")
      calculated_sums = self.calculate_sums(to_sum)
      print("Calculated sums:", calculated_sums)
      for path in calculated_sums.keys():
        sums[path] = calculated_sums[path]
        self.cache_insert_file(samplesums[path], sums[path]['sha1'], sums[path]['crc32'], os.path.getsize(path), os.path.getmtime(path))

    return sums


  def calculate_sums(self, filename_or_list):
    if isinstance(filename_or_list, str):
      return self._calculate_sums(filename_or_list)

    with Pool(self.threads) as p:
      sums = p.map(self._calculate_sums, filename_or_list)

    i = 0
    ret = {}
    for fn in filename_or_list:
      ret[fn] = sums[i]
      i = i + 1

    return ret

  def _calculate_sums(self, filename):
    if os.path.isdir(filename):
      return None

    file_size = os.path.getsize(filename)
    file_mtime = os.path.getmtime(filename)

    self.log("Running checksums for %s..." % filename)
    s = hashlib.sha1()
    crc32 = 0
    with open(filename, "r+b") as fd:
      while True:
        # Large chunk sizes make no meaningful difference; reduce memory consumption and use 64K chunks
        # https://stackoverflow.com/questions/17731660/hashlib-optimal-size-of-chunks-to-be-used-in-md5-update
        buf = fd.read(1024 * 64) # 64K
        if not buf:
          break
        # Changed in python 3: always returns an unsigned value.
        # "To generate the same numeric value across all Python versions and platforms, use crc32(data) & 0xffffffff."
        crc32 = zlib.crc32(buf, crc32) & 0xffffffff
        s.update(buf)

    sha1 = binascii.hexlify(s.digest()).decode('ascii')
    crc32 = "%08x" % crc32
   
    return {'sha1': sha1, 'crc32': crc32}


  def samplesum(self, filename_or_list):
    if isinstance(filename_or_list, str):
      return self._samplesum(filename_or_list)

    with Pool(self.threads) as p:
      sums = p.map(self._samplesum, filename_or_list)

    i = 0
    ret = {}
    for fn in filename_or_list:
      ret[fn] = sums[i]
      i = i + 1

    return ret

  def _samplesum(self, filename):
    if os.path.isdir(filename):
      return None

    # Total samples taken in bytes. Use something divisible by 4K (4096)
    total_sample_size = 1024 * 1024 * 10
    sample_count = 20
    #print("Sample size is %d" % sample_size)

    filesize = os.path.getsize(filename)

    if filesize <= total_sample_size:
      self.log("File is too small to samplesum; using SHA1")
      # Samplesum of files < the total sample size is just the sha1 of the file
      return self._calculate_sums(filename)['sha1']

    self.log("Samplesumming %s..." % filename)
    # Attempt to align with 4K blocks for seeks/reads
    blocks = filesize // 4096
    if filesize % 4096 > 0:
      blocks += 1

    sample_size = math.floor(total_sample_size / sample_count)
    s = hashlib.sha1()
    with open(filename, "r+b") as fd:
      # Evenly space sample_count sample points
      idx = 0
      stride = math.floor(blocks / sample_count)
      sample_i = 0
      while idx <= filesize - sample_size:
        #print("Sampling at position %d/%d (sample=%d mod4k=%d)" % (idx, filesize, sample_i, idx % 4096))
        fd.seek(idx)
        buf = fd.read(sample_size)
        if not buf:
          break
        s.update(buf)
        idx += stride * 4096
        sample_i += 1
    return binascii.hexlify(s.digest()).decode('ascii')

