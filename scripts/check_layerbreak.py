#!/usr/bin/env python3
import sys

def is_broken(path):
  with open(path, 'rb') as f:
    if not f.seek(0xE99D8000):
      raise Exception('cant seek to layerbreak')
    for i in range(0, 3):
      sector = f.read(2048)
      for x in sector:
        if x != 0:
          #print("found non-0 byte in sector %d" % i, x)
          return False
  return True

for p in sys.argv[1:]:
  if is_broken(p):
    print("%s: BAD" % p)
  else:
    print("%s: OK" % p)
