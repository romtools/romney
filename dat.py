import xml.etree.ElementTree as etree
import os, re

class RomFile:
  # For archives; indicates broken or empty archive
  error = ""
 
  # Absolute path to parent archive file, if applicable
  in_archive = None

  has_children = False


  def __init__(self, path, crc32='', sha1='', md5='', size=None, in_archive=None, is_dir=False, error=""):
    self.path = path
    self.crc32 = crc32.lower()
    self.sha1 = sha1.lower()
    self.md5 = md5.lower()
    self.size = size
    self.in_archive = in_archive
    self.error = error
    self.has_children = os.path.isdir(path) or path.endswith('.7z') or path.endswith('.zip')
    self.is_dir = is_dir
    self.games = []
    

  def prettyPath(self):
    if self.in_archive:
      return self.in_archive+'/'+self.path
    else:
      return self.path

class RomFileGroup(list):

  def addFile(self, romfile):
    self.append(romfile)
    self.collate()

  def findByBasename(self, basename, ext=[], include_archive_contents=False): 
    ret = RomFileGroup()
    for f in self:
      if '.'.join(os.path.basename(f.path).split('.')[:-1]) == basename:
        if ext and f.path.split('.')[-1] not in ext:
          continue
        if f.in_archive and not include_archive_contents:
          continue
        ret.addFile(f)
    return ret

  def getArchiveFiles(self, filename):
    ret = RomFileGroup() 
    for f in self:
      if f.in_archive == filename:
        ret.addFile(f)
    return ret

  def findByFilename(self, filename, include_archive_contents=False):
    for f in self:
      if os.path.basename(f.path) == os.path.basename(filename):
        if f.in_archive and not include_archive_contents:
          continue
        return f
    return False

  def findByCRCAndSize(self, crc32, size, exclude_archives = False):
    ret = RomFileGroup()
    for f in self:
      if f.in_archive and exclude_archives:
        continue
      if (f.crc32 == crc32) and (f.size == size):
        ret.addFile(f)
    return ret

  def deleteByPath(self, full_path):
    to_delete = []
    for i,f in enumerate(self):
      if f.path == full_path or (f.in_archive and f.in_archive == full_path):
        to_delete.append(i)
    to_delete.sort(reverse=True)
    for i in to_delete:
      del self[i]

  def deleteByCRC(self, crc32):
    to_delete = []
    for i,f in enumerate(self):
      if f.crc32 == crc32:
        to_delete.append(i)
    to_delete.sort(reverse=True)
    for i in to_delete:
      del self[i]

  def getSubPath(self, path):
    rg = RomFileGroup()
    for f in self:
      if f.path.startswith(path):
        rg.addFile(f)
    return rg

  def collate(self):
    self.sort(key=lambda ii: ii.path)

class Game:
  name = None
  files = None
  def __init__(self, name=None):
    self.name = name
    self.files = RomFileGroup()

  def addFile(self, romfile):
    self.files.addFile(romfile)

  def getFileBySHA1(self, sha1):
    for f in self.files:
      if f.sha1 == sha1:
        return f
    return None

  def getFileByCRC(self, crc32, size):
    for f in self.files:
      if f.crc32 == crc32 and f.size == size:
        return f
    return None


class DAT:
  def __init__(self, dat_path, include_countries=[], exclude_countries=[]):
    self.crcMap = {}
    self.md5Map = {}
    self.sha1Map = {}
    self.games = []
    with open(dat_path, 'r') as f:
      l = f.readline()
    if l.startswith('clr'):
      self._parseCLR(dat_path)
    else:
      self._parseXML(dat_path)

    print("[DAT] Parsed %d total games" % len(self.games))

    to_delete = []
    for i,g in enumerate(self.games):
      if include_countries:
        valid_country = False
        for c in include_countries:
          if g.name.find('(%s)' % c) != -1:
            valid_country = True
        if not valid_country:
          to_delete.append(i)

      for c in exclude_countries:
        if g.name.find('(%s)' % c) != -1:
          to_delete.append(i)
    
    if to_delete:
      to_delete.sort(reverse=True)
      num_deleted = 0
      for i in to_delete:
        num_deleted = num_deleted + 1
        del self.games[i]
      print("[DAT] Removing %d games due to country white/blacklist settings" % num_deleted)

    self.games.sort(key=lambda ii: ii.name)
  
  def _parseCLR(self, dat_path):
    print("[DAT] Parsing DAT as clrmamepro...")
    with open(dat_path, 'r') as clr_file:
      state = ''
      for l in clr_file:
        if l.startswith('game ('):
          state = 'game'
          this_game = Game()
          continue
        if l.startswith(')'):
          if state == 'game':
            # save this game
            self.games.append(this_game)
            state = ''
          continue
        if state == 'game':
          if l.lstrip().startswith('name'):
            this_game.name = re.search('name "(.*)"', l).group(1)
          if l.lstrip().startswith('rom'):
            # these are always on one line
            crc32 = re.search('crc (.{8})', l).group(1).lower()
            size = int(re.search('size (.*) crc', l).group(1))
            name = re.search('name "(.*)"', l).group(1)
            romfile = RomFile(name, crc32=crc, size=size)
            this_game.addFile(romfile)
            try:
              self.crcMap[crc32].append(this_game.name)
            except KeyError:
              self.crcMap[crc32] = [this_game.name]
  
  def _parseXML(self, dat_path):
    print("[DAT] Parsing DAT as XML...")
    tree = etree.parse(dat_path)
    dat_games = tree.findall('game')
    
    for g in dat_games:
      game = Game(g.attrib['name'])
      # print("[DAT] Got game %s" % g.attrib['name'])
      for r in g.iter('rom'):
        md5, crc32, sha1 = r.get('md5').lower(), r.get('crc').lower(), r.get('sha1').lower()
        size = int(r.get('size'))
        # print("[DAT] Got romfile %s | sha1 %s | md5 %s | crc %s" % (r.attrib['name'], sha1, md5, crc32))
        game.addFile(RomFile(r.attrib['name'], crc32=crc32, md5=md5, sha1=sha1, size=size))
        self.md5Map.setdefault(md5, []).append(game)
        self.sha1Map.setdefault(sha1, []).append(game)
        self.crcMap.setdefault(crc32, []).append({'size':size, 'game':game})
        """
        try:
          if md5:
            self.md5Map[md5].append(game)
          if sha1:
            self.sha1Map[sha1].append(game)
          if crc:
            self.crcMap[crc].append({'size':r.attrib['size'], 'game':game})
        except KeyError:
          self.md5Map[md5] = [game]
          self.sha1Map[sha1] = [game]
          self.crcMap[crc] = [{'size':r.attrib['size'], 'game':game}]
        """
      self.games.append(game)

  def findGameNamesByCRC(self, crc32, size):
    try:
      results = []
      for m in self.crcMap[crc32]:
        if m['size'] == size:
          results.append(m['game'])
      return results
    except KeyError:
      return []

  def findGamesByMD5(self, md5):
    try:
      return self.md5Map[md5]
    except KeyError:
      return []

  def findGamesBySHA(self, sha1sum):
    try:
      return self.sha1Map[sha1sum]
    except KeyError:
      return []

  def findGameByName(self, name):
    for g in self.games:
      if g.name == name:
        return g
