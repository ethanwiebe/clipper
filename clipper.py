#!/bin/python

import math,os,subprocess,argparse,time,hashlib

verbose = False
ffmpegDir = "ENTER_FFMPEG_DIR"
assert ffmpegDir != "ENTER_FFMPEG_DIR"
ffmpegPath = os.path.join(ffmpegDir,"ffmpeg.exe")
ffprobePath = os.path.join(ffmpegDir,"ffprobe.exe")

clipListName = 'tmpcliplist.txt'
clipDir = os.path.join('.','clips')
baseDir = ''
KEYFRAME_INT = 5
FADE_NOT_SET = -1.0
END_TIME_POS = -1.0
DEFAULT_AUTOFADE = 0.025

def GetColorString(col):
    return '0x'+(''.join((hex(i)[2:].zfill(2) for i in col))).upper()
    
def ForwardJoin(path1,path2):
    path1 = path1.replace('\\','/')
    path2 = path2.replace('\\','/')
    if path1:
        return '/'.join((path1,path2))
    return path2
    
def IsValidFPS(text):
    if text[0]=='0':
        return False
        
    if '/' in text:
        frac = text.split('/')
        if len(frac[0])==0 or len(frac[1])==0:
            return False
            
        if not frac[0].isnumeric() or not frac[1].isnumeric():
            return False
            
        if frac[1][0]=='0':
            return False
    else:
        if not text.isnumeric():
            return False
    return True
    
class VideoInfo:
    def __init__(self,path,w,h,fps,sampleRate):
        self.path = path
        self.width = w
        self.height = h
        self.fps = fps
        self.sampleRate = sampleRate
        
    
def GetVideoInfo(path):
    # video pass
    result = subprocess.run(
        [
            ffprobePath,
            "-v",
            "error",
            "-select_streams",
            "v",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines = result.stdout.decode('utf-8').strip().split('\n')
    lines = [i.strip() for i in lines]
    
    width = int(lines[0])
    height = int(lines[1])
    
    frac = lines[2].split('/')
    if float(frac[1])==1.0:
        rate = frac[0] # 30/1 -> 30
    else:
        rate = lines[2] # 30000/1001 -> 30000/1001
    
    # audio pass
    result = subprocess.run(
        [
            ffprobePath,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            "-show_entries",
            "stream=sample_rate",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    
    lines = result.stdout.decode('utf-8').strip().split('\n')
    lines = [i.strip() for i in lines]
    if lines:
        sampleRate = int(lines[0])
    else:
        sampleRate = 44100
    
    return VideoInfo(path,width,height,rate,sampleRate)
    
def ReencodeVideo(name):
    path = os.path.join(clipDir,name)
    newPath = os.path.join(clipDir,'tmpreencode'+name)
    
    cmd = [ffmpegPath,'-y','-loglevel','warning','-i',path,'-c:v','copy','-c:a','copy',newPath]
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    if res.returncode!=0:
        os.remove(newPath)
        return False
    
    os.replace(newPath,path)
    return True

class FadeData:
    def __init__(self,inLen=FADE_NOT_SET,outLen=FADE_NOT_SET):
        self.inLen = inLen
        self.outLen = outLen
        
    def __eq__(self,b):
        return self.inLen==b.inLen and self.outLen==b.outLen

class XFadeData:
    def __init__(self):
        self.style = 'fade'
        self.duration = 0.0
        
class FontDef:
    def __init__(self,name,fontPath,size):
        self.name = name
        self.fontPath = fontPath
        self.size = size
    
    def GetFontString(self):
        return ':'.join((
            f'fontsize={self.size}',
            f'fontfile={self.fontPath}'
        ))
        
        
class TextData:
    def __init__(self,fontDef,x='w/2-text_w/2',y='h/2-text_h/2',startTime=None,endTime=None,text='',color='white',fadeData=None,outlineW=0,outlineColor='black'):
        self.x = x
        self.y = y
        self.start = startTime
        self.end = endTime
        self.font = fontDef
        self.text = text
        self.outlineW = outlineW
        self.outlineColor = outlineColor
        self.color = color
        if fadeData is None:
            self.fadeData = FadeData()
        else:
            self.fadeData = fadeData
    
    def GetTextFilePath(self,index):
        return os.path.join(clipDir,f'txt{index}.txt')
    
    def GetFilterString(self,start,index):
        if type(self.color) is tuple:
            col = GetColorString(self.color)
        elif type(self.color) is str:
            col = self.color
        else:
            assert False
            
        assert self.start is not None and self.end is not None
        
        startT = start+self.start
        endT = start+self.end
        
        textfilePath = self.GetTextFilePath(index)
        textfilePath = textfilePath.replace('\\','/')
        
        filterArr = [
            self.font.GetFontString(),
            f"fontcolor={col}",
            f'x={self.x}',
            f'y={self.y}',
            # need to escape this
            f"textfile={textfilePath}",
            f"enable='between(t,{startT},{endT})'",
        ]
        
        if self.outlineW!=0:
            filterArr.extend((
                f"borderw={self.outlineW}",
                f"bordercolor={self.outlineColor}",
            ))
        
        if self.fadeData.inLen!=FADE_NOT_SET and self.fadeData.outLen!=FADE_NOT_SET:
            inLen = self.fadeData.inLen
            outLen = self.fadeData.outLen
            
            filterArr.extend((
                f"alpha='if(lt(t,{startT+inLen}),(t-{startT})/{inLen},if(lt(t,{endT-outLen}),1,1.0-((t-{endT-outLen})/{outLen})))'",
            ))
        
        filter = ':'.join(filterArr)
        return f'drawtext={filter}'

class AudioData:
    def __init__(self,inFile,start=0.0,end=END_TIME_POS,fade=None,delay=0.0,volume=1.0):
        self.inFile = inFile
        self.start = start
        self.end = end
        self.delay = delay
        self.volume = volume
        if fade is None:
            self.fadeData = FadeData()
        else:
            self.fadeData = fade
    
    def GetStateString(self):
        return ';'.join([
            self.inFile,
            str(round(self.start,3)),
            str(round(self.end,3)),
            str(round(self.fadeData.inLen,3)),
            str(round(self.fadeData.outLen,3)),
            str(int(self.delay*1000)),
            str(round(self.volume,3))
        ])
        
        
class GenData:
    def __init__(self,genType,length,color='black',imagePath=None,format='.mp4',fade=None,texts=None,lineNum=-1):
        self.genType = genType
        self.length = length
        self.format = format
        self.color = color
        self.imagePath = imagePath
        if fade is None:
            self.fadeData = FadeData()
        else:
            self.fadeData = fade
        
        if texts is None:
            self.texts = []
        else:
            self.texts = texts
            
        self.ComputeHashes()
        self.lineNum = lineNum
    
    def GenerateTextFiles(self):
        for i,text in enumerate(self.texts):
            textPath = text.GetTextFilePath(i)
            with open(textPath,'w') as f:
                f.write(text.text)
    
    def CleanTextFiles(self):
        for i,text in enumerate(self.texts):
            textPath = text.GetTextFilePath(i)
            if os.path.exists(textPath):
                os.remove(textPath)
        
    def ComputeHashes(self):
        self.textsHash = self.GetTextsHash()
        
    def GetLength(self):
        return self.length
    
    def GetStateString(self):
        genArg = self.color
        if self.genType=='image':
            genArg = self.imagePath+';'+self.color
        arr = [
            'gen',
            self.genType,
            self.format,
            genArg,
            str(round(self.length,3)),
            str(self.fadeData.inLen),
            str(self.fadeData.outLen),
            self.textsHash,
        ]
        
        return ';'.join(arr)
        
    def GetTextsHash(self):
        h = hashlib.sha256()
        for i,text in enumerate(self.texts):
            h.update(bytes(text.GetFilterString(0.0,i),'utf8'))
            h.update(bytes(text.text,'utf8'))
        return h.hexdigest()[:10]
    
    def GetName(self):
        inFormat = self.format
        hashS = self.GetStateString()
        
        enc = 'utf8'
        nameHash = hashlib.sha256(bytes(hashS,enc)).hexdigest()[:12]
        
        name = f'gen{nameHash}{inFormat}'
        return name
        
    def __hash__(self):
        return hash(self.GetName())
        
    def __eq__(self,b):
        if type(b) is str:
            return self.GetName()==b
        else:
            return self.GetName()==b.GetName()
        
    def __repr__(self):
        return self.GetStateString()


class ScaleData:
    def __init__(self,x,y,w,h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
    
    def GetStateString(self):
        return ';'.join((str(self.x),str(self.y),str(self.w),str(self.h)))


class ClipData:
    def __init__(self,inFile,start,end,format='.mp4',scale=None,fade=None,autofade=0.0,texts=None,subclips=None,audios=None,volume=1.0,lineNum=-1):
        if inFile:
            self.inFile = os.path.relpath(inFile)
        else:
            self.inFile = ''
        self.format = format
        self.start = start
        self.end = end
        self.volume = volume
        if fade is None:
            self.fadeData = FadeData()
        else:
            self.fadeData = fade
        self.autoFade = autofade
        
        if texts is None:
            self.texts = []
        else:
            self.texts = texts
        
        self.xfade = None
        
        if scale is None:
            self.scale = ScaleData(0,0,0,0)
        else:
            self.scale = scale
            
        if subclips is None:
            self.subClips = []
        else:
            self.subClips = subclips
        
        if audios is None:
            self.audios = []
        else:
            self.audios = audios
        
        self.ComputeHashes()
        
        self.lineNum = lineNum
        
    def GenerateTextFiles(self):
        name = self.GetName()
        for i,text in enumerate(self.texts):
            textPath = text.GetTextFilePath(i)
            with open(textPath,'w') as f:
                f.write(text.text)
    
    def CleanTextFiles(self):
        name = self.GetName()
        for i,text in enumerate(self.texts):
            textPath = text.GetTextFilePath(i)
            if os.path.exists(textPath):
                os.remove(textPath)
    
    def ComputeHashes(self):
        self.textsHash = self.GetTextsHash()
        self.subClipsHash = self.GetSubClipsHash()
        self.audiosHash = self.GetAudiosHash()
    
    def GetLength(self):
        assert self.end>=0.0
        return self.end-self.start
        
    def GetAudioFilterString(self):
        cmd = ['[0:a]adelay=0:all=true[out0]']
        final = ['[out0]']
            
        for i,audio in enumerate(self.audios):
            index = i+1
            delay = int(audio.delay*1000)
            v = round(audio.volume,3)
            if audio.start>0.0:
                assert audio.end!=END_TIME_POS
                cmd.append(f'[{index}:a]atrim={audio.start}:{audio.end}[trim{index}]')
                cmd.append(f'[trim{index}]volume={v}[vol{index}]')
            else:
                cmd.append(f'[{index}]volume={v}[vol{index}]')
            
            if audio.fadeData.inLen!=FADE_NOT_SET or audio.fadeData.outLen!=FADE_NOT_SET:
                inFilter = ''
                outFilter = ''
                if audio.fadeData.inLen!=FADE_NOT_SET:
                    inFilter = f'afade=t=in:st={round(audio.start,3)}:d={round(audio.fadeData.inLen,3)}'
                if audio.fadeData.outLen!=FADE_NOT_SET:
                    endT = audio.end-audio.delay-audio.fadeData.outLen
                    outFilter = f'afade=t=out:st={round(endT,3)}:d={round(audio.fadeData.outLen,3)}'
                
                if inFilter and outFilter:
                    fadeFilter = f'{inFilter},{outFilter}'
                elif inFilter:
                    fadeFilter = inFilter
                else:
                    fadeFilter = outFilter
                cmd.append(f'[vol{index}]{fadeFilter}[fade{index}]')
                cmd.append(f'[fade{index}]adelay={delay}:all=true[a{index}]')
            else:
                cmd.append(f'[vol{index}]adelay={delay}:all=true[a{index}]')
            final.append(f'[a{index}]')
        
        final = ''.join(final)
        final += f'amix=inputs={len(self.audios)+1}:normalize=0:duration=first[out]'
        
        cmd.append(final)
        audioFilter = ';'.join(cmd)
        return audioFilter
        
    def GetTextsHash(self):
        h = hashlib.sha256()
        for i,text in enumerate(self.texts):
            h.update(bytes(text.GetFilterString(self.start,i),'utf8'))
            h.update(bytes(text.text,'utf8'))
        return h.hexdigest()[:10]
    
    def GetSubClipsHash(self):
        h = hashlib.sha256()
        for subclip in self.subClips:
            h.update(bytes(subclip.GetStateString(),'utf8'))
        return h.hexdigest()[:10]
    
    def GetAudiosHash(self):
        h = hashlib.sha256()
        for audio in self.audios:
            h.update(bytes(audio.GetStateString(),'utf8'))
        return h.hexdigest()[:10]
    
    def GetStateString(self):
        assert self.end>=0.0
        arr = [
            'clip',
            self.inFile,
            self.format,
            str(round(self.start,3)),
            str(round(self.end,3)),
            str(round(self.volume,3)),
            str(self.fadeData.inLen),
            str(self.fadeData.outLen),
            str(self.autoFade),
            self.scale.GetStateString(),
            self.textsHash,
            self.subClipsHash,
            self.audiosHash
        ]
        
        if self.xfade is None:
            arr.append('-1')
        else:
            arr.append(self.xfade.style)
            arr.append(str(round(self.xfade.duration,3)))
        
        return ';'.join(arr)
    
    def GetName(self):
        inFormat = self.format
        hashS = self.GetStateString()
        
        enc = 'utf8'
        nameHash = hashlib.sha256(bytes(hashS,enc)).hexdigest()[:12]
        if not self.subClips:
            name = f'clip{nameHash}{inFormat}'
        else:
            if self.xfade is not None:
                name = f'xfade{nameHash}{inFormat}'
            else:
                name = f'join{nameHash}{inFormat}'
            
        return name
        
    def __hash__(self):
        return hash(self.GetName())
        
    def __eq__(self,b):
        if type(b) is str:
            return self.GetName()==b
        else:
            return self.GetName()==b.GetName()
        
    def __repr__(self):
        return self.GetStateString()
        

class ClipSpec:
    def __init__(self):
        self.outFile = ''
        self.fps = ''
        self.width = 0
        self.height = 0
        self.sampleRate = 0
        self.clip = ClipData('',0.0,0.0)
        self.fontDefs = {}
        

def VerbosePrint(msg,end='\n'):
    if verbose:
        print(msg,end=end)
    

def ConvertTime(timestamp):
    sections = timestamp.split(':')
    if len(sections)>3 or len(sections)<1:
        return None
    if len(sections)==1:
        try:
            t = float(sections[0])
        except ValueError:
            return None
    elif len(sections)==2:
        try:
            minutes = int(sections[0])
            seconds = float(sections[1])
            t = seconds+minutes*60
        except ValueError:
            return None
    elif len(sections)==3:
        try:
            hours = int(sections[0])
            minutes = int(sections[1])
            seconds = float(sections[2])
            t = seconds+minutes*60+hours*60*60
        except ValueError:
            return None
    
    return t

def GetTimeString(seconds):
    millis = math.floor(seconds*1000)%1000
    secs = math.floor(seconds)%60
    minutes = (math.floor(seconds)//60)%60
    hours = math.floor(seconds)//3600
    if hours:
        return f'{hours}:{str(minutes).zfill(2)}:{str(secs).zfill(2)}.{str(millis).zfill(3)}'
    if minutes:
        return f'{minutes}:{str(secs).zfill(2)}.{str(millis).zfill(3)}'
    return f'{secs}.{str(millis).zfill(3)}'

def GetSeekTime(timestamp):
    t = math.floor(timestamp)
    # move back half a keyframe, quantize to nearest keyframe
    t = int(max(math.floor((t-KEYFRAME_INT/2)/KEYFRAME_INT)*KEYFRAME_INT,0))
    return t
    
def GetCmdPrefix(spec,inFile,seekPos):
    assert spec.fps!='' and spec.width!=0 and spec.height!=0
    return [ffmpegPath,'-y','-loglevel','warning','-ss',
              str(seekPos),'-i',inFile,
              '-r',spec.fps,'-s',f'{spec.width}x{spec.height}']

def GetFadeFilter(fadeData,start,end,autoLen):
    afadeIn = ''
    afadeOut = ''
    vfadeIn = ''
    vfadeOut = ''
    
    if fadeData.inLen!=FADE_NOT_SET:
        fadeInStart = round(start,3)
        afadeIn = f'afade=t=in:st={fadeInStart}:d={fadeData.inLen}'
        vfadeIn = f'fade=t=in:st={fadeInStart}:d={fadeData.inLen}'
    elif autoLen:
        fadeInStart = round(start,3)
        afadeIn = f'afade=t=in:st={fadeInStart}:d={autoLen}'
    
    if fadeData.outLen!=FADE_NOT_SET:
        fadeOutStart = round(end,3)-fadeData.outLen
        afadeOut = f'afade=t=out:st={fadeOutStart}:d={fadeData.outLen}'
        vfadeOut = f'fade=t=out:st={fadeOutStart}:d={fadeData.outLen}'
    elif autoLen:
        fadeOutStart = round(end,3)-autoLen
        afadeOut = f'afade=t=out:st={fadeOutStart}:d={autoLen}'
    
    afade = afadeIn
    if afadeOut:
        if afade:
            afade += ','
        afade += afadeOut
        
    vfade = vfadeIn
    if vfadeOut:
        if vfade:
            vfade += ','
        vfade += vfadeOut
    return afade,vfade
              
def GenerateXFadeCmd(spec,clip):
    assert len(clip.subClips)==2
    aClip = clip.subClips[0]
    bClip = clip.subClips[1]
    aName = os.path.join(clipDir,aClip.GetName())
    bName = os.path.join(clipDir,bClip.GetName())
    
    prefix = [ffmpegPath,'-y','-loglevel','warning','-i',aName,'-i',bName]
            
    offset = aClip.GetLength()-clip.xfade.duration
    xfilter = f'[0:v][1:v]xfade=transition={clip.xfade.style}:duration={round(clip.xfade.duration,3)}:offset={offset}[video]'
    afilter = f'[0:a][1:a]acrossfade=d={round(clip.xfade.duration,3)}[audio]'
    f = f'{xfilter};{afilter}'
    outPath = os.path.join(clipDir,clip.GetName())
    cmd = prefix+['-filter_complex',f,'-map','[video]','-map','[audio]',outPath]
    return cmd

def GenerateGenCmd(spec,clip,outNameOverride=''):
    name = clip.GetName()
    if outNameOverride:
        outPath = outNameOverride
    else:
        outPath = os.path.join(clipDir,name)
        
    prefix = [ffmpegPath,'-y','-loglevel','warning']
    
    vf = ''
    
    postfix = []
    if clip.genType=='color':
        genFilter = f'color=c={clip.color}:s={spec.width}x{spec.height}:d={round(clip.length,3)}:r={spec.fps}'
        postfix = ['-f','lavfi','-i',genFilter]
    elif clip.genType=='image':
        #genFilter = f'color=c={clip.color}:s={spec.width}x{spec.height}:d={round(clip.length,3)}:r={spec.fps}'
        postfix = [
            '-framerate',str(spec.fps),'-i',clip.imagePath,'-t',str(clip.length),'-pix_fmt','yuv420p',
        ]
        vf += f'scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease,pad={spec.width}:{spec.height}:-1:-1:color={clip.color},loop=-1:1'
        
    cmd = prefix
    cmd.append('-f')
    cmd.append('lavfi')
    cmd.append('-i')
    sampleRate = spec.sampleRate
    if not sampleRate:
        sampleRate = 44100
    cmd.append(f'anullsrc=channel_layout=stereo:sample_rate={sampleRate}')
    cmd.extend(postfix)
    if clip.genType=='color':
        cmd.append('-shortest')
    
    textFilter = ','.join((t.GetFilterString(0.0,i) for i,t in enumerate(clip.texts)))
    if textFilter:
        if vf:
            vf += ','
        vf += textFilter
    
    afade,vfade = GetFadeFilter(clip.fadeData,0.0,clip.GetLength(),0.0)
    if vfade:
        if vf:
            vf += ','
        vf += vfade
        
    if vf:
        cmd.append('-vf')
        cmd.append(vf)
        
    cmd.append(outPath)
    return cmd

def GenerateCmd(spec,clip,outNameOverride=''):
    name = clip.GetName()
    if outNameOverride:
        outPath = outNameOverride
        if clip.audios:
            outPath = os.path.join(clipDir,'unmixed'+os.path.basename(outPath))
    else:
        if clip.audios:
            outPath = os.path.join(clipDir,'unmixed'+name)
        else:
            outPath = os.path.join(clipDir,name)
    
    inFile = clip.inFile
    if clip.subClips:
        if clip.xfade is not None:
            return GenerateXFadeCmd(spec,clip)
            
        if len(clip.subClips)>1:
            inFile = os.path.join(clipDir,'tmp'+name)
        else:
            inFile = os.path.join(clipDir,clip.subClips[0].GetName())
            

    q = GetSeekTime(clip.start)
    start = clip.start-q
    end = clip.end-q
    
    autoFadeLen = clip.autoFade
    # prevent re-fading clips' audio
    if clip.subClips:
        autoFadeLen = 0.0
    
    prefix = GetCmdPrefix(spec,inFile,q)
    
    volFilter = ''
    if clip.volume!=1.0:
        volFilter = f'volume={round(clip.volume,3)}'
    textFilter = ','.join((t.GetFilterString(start,i) for i,t in enumerate(clip.texts)))
    
    afade,vfade = GetFadeFilter(clip.fadeData,start,end,autoFadeLen)
    
    if volFilter:
        if afade:
            afade += ','
        afade += volFilter
    if textFilter:
        if vfade:
            vfade += ','
        vfade += textFilter
    
    if vfade:
        prefix.append('-vf')
        prefix.append(vfade)
    if afade:
        prefix.append('-af')
        prefix.append(afade)
    
    if outNameOverride:
        # final output clip
        if vfade and afade:
            cmd = prefix+['-movflags','faststart',outPath]
        elif vfade:
            cmd = prefix+['-c:a','copy','-movflags','faststart',outPath]
        elif afade:
            cmd = prefix+['-c:v','copy','-movflags','faststart',outPath]
        else:
            cmd = prefix+['-c:v','copy','-c:a','copy','-movflags','faststart',outPath]
    else:
        cmd = prefix+['-ss',str(round(start,3)),'-to',str(round(end,3)),outPath]
    return cmd
        
class ClipParser:
    def __init__(self,file):
        self.file = file
        self.currLine = ''
        self.lineNum = 0
    
    def NextLine(self):
        self.currLine = ''
        while self.currLine=='':
            self.currLine = self.file.readline()
            self.lineNum += 1
            if self.currLine=='':
                return False
                
            self.currLine = self.currLine.strip()
            
        return True
        
    def Tokenize(self,text):
        text = text.strip()
        
        toks = []
        strMode = ''
        escape = False
        
        currTok = ''
        for c in text:
            if strMode:
                if c not in (strMode,'\\') or escape:
                    currTok += c
                    escape = False
                elif c=='\\':
                    escape = True
                else:
                    strMode = ''
                    # can be ''
                    toks.append(currTok)
                    currTok = ''
            else:
                if c=="'" or c=='"':
                    strMode = c
                elif not c.isspace():
                    currTok += c
                else:
                    if currTok:
                        toks.append(currTok)
                    currTok = ''
        
        # string was not terminated
        if strMode:
            self.PrintError("unterminated string literal")
            return None
            
        if currTok:
            toks.append(currTok)
            
        return toks
    
    def ParseFloat(self,token):
        try:
            f = float(token)
            return f
        except ValueError:
            return None
    
    def ParseInt(self,token):
        try:
            i = int(token)
            return i
        except ValueError:
            return None
            
    def ParseVolume(self,line):
        tokens = self.Tokenize(line)
        if tokens is None:
            return None
            
        if len(tokens)!=2:
            self.PrintError(f'expected 2 tokens, got {len(tokens)}')
            return None
        
        f = self.ParseFloat(tokens[1])
        if f is None:
            self.PrintError(f'could not parse volume!')
            return None
            
        return f
    
    def ParseZoom(self,line,vidWidth,vidHeight):
        tokens = self.Tokenize(line)
        if tokens is None:
            return None
        
        if len(tokens)!=5:
            self.PrintError(f'expected \'zoom X1 Y1 X2 Y2\'')
            return None
        
        if len(list(filter(lambda x:x=='.',tokens)))>1:
            self.PrintError('only one arg of zoom can be \'.\'')
            return None
        
        if tokens[1]=='.':
            x1 = -1
        else:
            x1 = self.ParseInt(tokens[1])
            if x1 is None:
                self.PrintError(f'could not parse zoom x1 position!')
                return None
        if tokens[2]=='.':
            y1 = -1
        else:
            y1 = self.ParseInt(tokens[2])
            if y1 is None:
                self.PrintError(f'could not parse zoom y1 position!')
                return None
        
        if tokens[3]=='.':
            x2 = -1
        else:
            x2 = self.ParseInt(tokens[3])
            if x2 is None:
                self.PrintError(f'could not parse zoom x2 position!')
                return None
        if tokens[4]=='.':
            y2 = -1
        else:
            y2 = self.ParseInt(tokens[4])
            if y2 is None:
                self.PrintError(f'could not parse zoom y2 position!')
                return None
        
        if x1==-1:
            h = y2-y1
            w = int(h/vidHeight*vidWidth)
            x1 = x2-w
        elif y1==-1:
            w = x2-x1
            h = int(w/vidWidth*vidHeight)
            y1 = y2-h
        elif x2==-1:
            h = y2-y1
            w = int(h/vidHeight*vidWidth)
        elif y2==-1:
            w = x2-x1
            h = int(w/vidWidth*vidHeight)
        else:
            w = x2-x1
            h = y2-y1
            
        if w<=0:
            self.PrintError('zoom x2 must be smaller than x1!')
            return None
        if h<=0:
            self.PrintError('zoom y2 must be smaller than y1!')
            return None
        
        return ScaleData(x1,y1,w,h)
    
    def ParseXFadeStmt(self,line):
        xFadeData = XFadeData()
        tokens = self.Tokenize(line)
        if tokens is None:
            return None
            
        if len(tokens)!=3:
            self.PrintError(f'expected 3 tokens, got {len(tokens)}')
            return None
        
        # check that this is a real style?
        xFadeData.style = tokens[1]
        f = self.ParseFloat(tokens[2])
        if f is None:
            self.PrintError(f'could not parse xfade length!')
            return None
        xFadeData.duration = f
        return xFadeData
    
    def ParseFadeStmt(self,line):
        fadeData = FadeData()
        tokens = self.Tokenize(line)
        if tokens is None:
            return None
        
        if len(tokens)!=3:
            self.PrintError(f'expected 3 tokens, got {len(tokens)}')
            return None
        
        if tokens[1]=='in':
            f = self.ParseFloat(tokens[2])
            if f is None:
                self.PrintError(f'could not parse float for fade length!')
                return None
            fadeData.inLen = f
        elif tokens[1]=='out':
            f = self.ParseFloat(tokens[2])
            if f is None:
                self.PrintError(f'could not parse float for fade length!')
                return None
            fadeData.outLen = f
        elif tokens[1]=='inout':
            f = self.ParseFloat(tokens[2])
            if f is None:
                self.PrintError(f'could not parse float for fade length!')
                return None
            fadeData.inLen = f
            fadeData.outLen = f
        else:
            self.PrintError(f'expected \'in\', \'out\', or \'inout\' after \'fade\', not \'{tokens[1]}\'')
            return None
        
        return fadeData
        
    def ParseFontDef(self,line):
        # font fontfile.ttf size
        toks = self.Tokenize(line)
        if toks is None:
            return None
        
        assert toks[0]=='font'
        
        if len(toks)>4:
            self.PrintError('too many tokens supplied to font def!')
            return None
        if len(toks)<3:
            self.PrintError('too few tokens supplied to font def!')
            return None
        
        name = toks[1]
        path = toks[2]
        if not os.path.isabs(path):
            path = ForwardJoin(baseDir,path)
            
        if not os.path.isfile(path):
            self.PrintError(f'font file \'{path}\' not found!')
            return None
        
        size = 48
        if len(toks)==4:
            size = self.ParseInt(toks[3])
            if size is None:
                self.PrintError('expected int for font size!')
                return None
            
        fontDef = FontDef(name,path,size)
        return fontDef
        
    def ParseTimeCode(self,token):
        f = self.ParseFloat(token)
        if f is None:
            f = ConvertTime(token)
            if f is None:
                self.ParseError(f'could not parse \'{token}\' as a timecode!')
                return None
        
        return f
        
    def ParseCut(self,line):
        toks = self.Tokenize(line)
        if toks is None:
            return None
        
        assert toks[0]=='cut'
        if len(toks)!=3:
            self.PrintError('cut syntax: cut START END')
            return None
        
        # TODO: parse times properly
        start = self.ParseTimeCode(toks[1])
        if start is None:
            return None
        
        if toks[2]=='.':
            end = END_TIME_POS
        else:
            end = self.ParseTimeCode(toks[2])
            if end is None:
                return None
            
        return (start,end)
    
    def PrintError(self,err):
        print(f'Parse error at line {self.lineNum}: {err}')
        

def ParseTextBlock(parser,spec):
    toks = parser.Tokenize(parser.currLine)
    if toks is None:
        return None
        
    if len(toks)!=2:
        parser.PrintError(f'expected 2 tokens, got {len(toks)}')
        return None
        
    font = toks[1]
    if font not in spec.fontDefs:
        parser.PrintError(f'\'{font}\' is not a font!')
        return None
    
    fontDef = spec.fontDefs[font]
    td = TextData(fontDef)
    
    while True:
        if not parser.NextLine():
            parser.PrintError('ran out of lines while parsing text!')
            return None
        
        if parser.currLine[0]=='#':
            continue
        
        if parser.currLine.startswith('color '):
            # parse color
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
                
            if len(toks)!=2:
                parser.PrintError('color syntax: color NAME | color #rrggbb')
                return None
                
            td.color = toks[1]
        elif parser.currLine.startswith('pos '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
                
            if len(toks)!=3:
                parser.PrintError('pos syntax: pos X Y')
                return None
            
            td.x = toks[1]
            td.y = toks[2]
        elif parser.currLine.startswith('fade '):
            newFadeData = parser.ParseFadeStmt(parser.currLine)
            if newFadeData is None:
                parser.PrintError('could not parse fade statement!')
                return None
            
            if newFadeData.inLen!=FADE_NOT_SET:
                td.fadeData.inLen = newFadeData.inLen
            if newFadeData.outLen!=FADE_NOT_SET:
                td.fadeData.outLen = newFadeData.outLen
        elif parser.currLine.startswith('outline '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            
            if len(toks)<2 or len(toks)>3:
                parser.PrintError('outline syntax: outline WIDTH [COLOR]')
                return None
            
            if len(toks)==3:
                td.outlineColor = toks[2]
                
            i = parser.ParseInt(toks[1])
            if i is None:
                parser.PrintError('could not parse outline width!')
                return None
                
            td.outlineW = i
        elif parser.currLine.startswith('cut '):
            cut = parser.ParseCut(parser.currLine)
            if cut is None:
                parser.PrintError('could not parse cut statement!')
                return None
            td.start = cut[0]
            td.end = cut[1]
        elif parser.currLine=='end':
            break
        else:
            if parser.currLine[0] == '"' or parser.currLine[0] == "'":
                if parser.currLine[-1]!=parser.currLine[0]:
                    parser.PrintError('string was not terminated!')
                    return None
                    
                td.text = parser.currLine[1:-1]
                td.text = td.text.replace('\\','\\\\')
            else:
                parser.PrintError(f'unexpected line \'{parser.currLine}\'')
                return None
    
    if td.text=='':
        parser.PrintError('no text was specified!')
        return None
    
    return td

def ParseGen(parser,spec):
    fadeData = FadeData()
    gen = GenData(None,1.0)
    while True:
        if not parser.NextLine():
            parser.PrintError(f'ran out of lines while parsing gen block!')
            return None
        
        if parser.currLine[0]=='#':
            continue
        
        if parser.currLine.startswith('len '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            if len(toks)!=2:
                parser.PrintError(f'expected 2 tokens, got {len(toks)}')
                return None
            
            gen.length = parser.ParseFloat(toks[1])
            if gen.length is None:
                parser.PrintError(f'could not parse gen length!')
                return None
        elif parser.currLine.startswith('image '):
            gen.genType = 'image'
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            
            if len(toks)!=2:
                parser.PrintError('image syntax: image PATH')
                return None
            
            gen.imagePath = toks[1]
            if not os.path.isabs(gen.imagePath):
                gen.imagePath = os.path.join(baseDir,gen.imagePath)
            if not os.path.exists(gen.imagePath):
                parser.PrintError(f'image at path \'{gen.imagePath}\' does not exist!')
                return None
        elif parser.currLine.startswith('color '):
            if gen.genType is None:
                gen.genType = 'color'
            
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
                
            if len(toks)!=2:
                parser.PrintError('color syntax: color NAME | color #rrggbb')
                return None
                
            gen.color = toks[1]
        elif parser.currLine.startswith('fade '):
            newFadeData = parser.ParseFadeStmt(parser.currLine)
            if newFadeData is None:
                parser.PrintError('could not parse fade statement!')
                return None
            
            if newFadeData.inLen!=FADE_NOT_SET:
                gen.fadeData.inLen = newFadeData.inLen
            if newFadeData.outLen!=FADE_NOT_SET:
                gen.fadeData.outLen = newFadeData.outLen
        elif parser.currLine.startswith('text '):
            startLine = parser.lineNum
            text = ParseTextBlock(parser,spec)
            
            if text is None:
                parser.lineNum = startLine
                parser.PrintError(f'could not parse text! (syntax: text fontDef x y "text" [color]')
                return None
                
            gen.texts.append(text)
        elif parser.currLine == 'end':
            break
        else:
            parser.PrintError(f'unexpected line \'{parser.currLine}\'')
            return None
            
    if gen.genType is None:
        gen.genType = 'color'
    
    for text in gen.texts:
        # fix text timestamps if none were provided
        if text.start is None:
            text.start = 0.0
        if text.end is None:
            text.end = gen.length
        
    gen.ComputeHashes()
    return gen
    
def ParseAudio(parser,spec,currInFile):
    audio = AudioData(currInFile,start=None,end=None)
    
    while True:
        if not parser.NextLine():
            parser.PrintError(f'ran out of lines while parsing audio! (from line {startLine})')
            return None
        
        if parser.currLine[0]=='#':
            continue
        
        if parser.currLine.startswith('in '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            if len(toks)!=2:
                parser.PrintError(f'expected 2 tokens, got {len(toks)}')
                return None
                
            audio.inFile = toks[1].strip()
            if not os.path.isabs(audio.inFile):
                audio.inFile = os.path.join(baseDir,audio.inFile)
            if not os.path.exists(audio.inFile):
                parser.PrintError(f"audio path '{audio.inFile}' does not exist!")
                return None
                
        elif parser.currLine.startswith('cut '):
            if audio.start is not None and audio.end is not None:
                parser.PrintError('multiple cut statements found in one audio block!')
                return None
            
            cut = parser.ParseCut(parser.currLine)
            if cut is None:
                parser.PrintError('could not parse cut statement!')
                return None
                
            audio.start = cut[0]
            audio.end = cut[1]
        elif parser.currLine.startswith('volume '):
            audio.volume = parser.ParseVolume(parser.currLine)
            if audio.volume is None:
                parser.PrintError('could not parse volume!')
                return None
        elif parser.currLine.startswith('delay '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            if len(toks)!=2:
                parser.PrintError(f'expected 2 tokens, got {len(toks)}')
                return None
            
            d = parser.ParseFloat(toks[1])
            if d is None:
                parser.PrintError('could not parse delay time!')
                return None
            
            audio.delay = d
        elif parser.currLine.startswith('fade '):
            newFadeData = parser.ParseFadeStmt(parser.currLine)
            if newFadeData is None:
                parser.PrintError('could not parse fade statement!')
                return None
            
            if newFadeData.inLen!=FADE_NOT_SET:
                audio.fadeData.inLen = newFadeData.inLen
            if newFadeData.outLen!=FADE_NOT_SET:
                audio.fadeData.outLen = newFadeData.outLen
        elif parser.currLine == 'end':
            break
        else:
            parser.PrintError(f'unexpected line \'{parser.currLine}\'')
            return None
    
    if audio.start is None:
        audio.start = 0.0
    if audio.end is None:
        audio.end = END_TIME_POS
    if audio.inFile is None:
        parser.PrintError('no audio input specified!')
        return None
        
    return audio

def ParseClip(parser,spec,currInFile,currAutoFade,top=False):
    clip = ClipData(currInFile,start=None,end=None)
    if spec.outFile:
        clip.format = os.path.splitext(spec.outFile)[1]
    clip.autoFade = currAutoFade
    
    clip.lineNum = parser.lineNum
    pendingXFadeClip = None
    
    while True:
        if not parser.NextLine():
            if not top:
                parser.PrintError(f'ran out of lines while parsing clip! (from line {startLine})')
                return None
            else:
                break
        
        if parser.currLine[0]=='#':
            continue
        
        if parser.currLine.startswith('in '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            if len(toks)!=2:
                parser.PrintError(f'expected 2 tokens, got {len(toks)}')
                return None
                
            clip.inFile = toks[1].strip()
            if not os.path.isabs(clip.inFile):
                clip.inFile = os.path.join(baseDir,clip.inFile)
            if not os.path.exists(clip.inFile):
                parser.PrintError(f'input file \'{clip.inFile}\' does not exist!')
                return None
                
            info = GetVideoInfo(clip.inFile)
            if spec.fps=='':
                spec.fps = info.fps
            if spec.width==0:
                spec.width = info.width
            if spec.height==0:
                spec.height = info.height
            if spec.sampleRate==0:
                spec.sampleRate = info.sampleRate
        elif parser.currLine.startswith('out '):
            if not top:
                parser.PrintError(f'can only set output in global scope!')
                return None
            
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            if len(toks)!=2:
                parser.PrintError(f'expected 2 tokens, got {len(toks)}')
                return None
            if spec.outFile:
                parser.PrintError(f'output file was set twice!')
                return None
                
            spec.outFile = os.path.join(baseDir,toks[1].strip())
            clip.format = os.path.splitext(spec.outFile)[1]
            if not clip.format:
                parser.PrintError('output file has no extension!')
                return None
                
        elif parser.currLine.startswith('fps '):
            if not top:
                parser.PrintError(f'can only set fps in global scope!')
                return None
                
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
                
            if len(toks)!=2:
                parser.PrintError(f'fps syntax: fps FPS_VALUE')
                return None
                
            if spec.fps!='':
                parser.PrintError(f'fps has already been set!')
                return None
            
            fpsVal = toks[1]
            if fpsVal=='ntsc':
                fpsVal = '30000/1001'
            elif fpsVal=='ntsc60':
                fpsVal = '60000/1001'
            elif not IsValidFPS(fpsVal):
                parser.PrintError(f'invalid fps value!')
                return None
            
            spec.fps = fpsVal
        elif parser.currLine.startswith('res '):
            if not top:
                parser.PrintError(f'can only set resolution in global scope!')
                return None
                
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
                
            if len(toks)!=3:
                parser.PrintError(f'res syntax: res W H')
            
            if spec.width!=0 and spec.height!=0:
                parser.PrintError(f'resolution has already been set!')
                return None
            
            w = parser.ParseInt(toks[1])
            if w is None:
                parser.PrintError(f'expected int for width, not \'{toks[1]}\'')
                return None
            h = parser.ParseInt(toks[2])
            if h is None:
                parser.PrintError(f'expected int for height, not \'{toks[2]}\'')
                return None
            spec.width = w
            spec.height = h
        elif parser.currLine.startswith('autofade '):
            toks = parser.Tokenize(parser.currLine)
            if toks is None:
                return None
            
            if len(toks)!=2:
                parser.PrintError('autofade syntax: autofade SECONDS')
                return None
            
            clip.autoFade = parser.ParseFloat(toks[1])
            if clip.autoFade is None:
                parser.PrintError('could not parse float for autofade!')
                return None
        elif parser.currLine.startswith('font '):
            if not top:
                parser.PrintError(f'can only create fonts in global scope!')
                return None
                
            fontDef = parser.ParseFontDef(parser.currLine)
            if fontDef is None:
                parser.PrintError('could not parse font def! (syntax: font NAME FONT_PATH [SIZE])')
                return None
            
            spec.fontDefs[fontDef.name] = fontDef
        elif parser.currLine == 'audio':
            startLine = parser.lineNum
            audio = ParseAudio(parser,spec,clip.inFile)
            if audio is None:
                parser.lineNum = startLine
                parser.PrintError('could not parse audio!')
                return None
            if clip.subClips and clip.end is not None:
                audio.delay += clip.end
            clip.audios.append(audio)
        elif parser.currLine == 'clip' or parser.currLine == 'gen' or (parser.currLine.startswith('cut ') and top):
            if not spec.outFile:
                parser.PrintError('must set output file path!')
                return None
                
            startLine = parser.lineNum
            if parser.currLine == 'clip':
                subclip = ParseClip(parser,spec,clip.inFile,clip.autoFade)
                if subclip is None:
                    parser.lineNum = startLine
                    parser.PrintError('could not parse subclip!')
                    return None
                
                clip.subClips.append(subclip)
            elif parser.currLine == 'gen':
                subclip = ParseGen(parser,spec)
                if subclip is None:
                    parser.lineNum = startLine
                    parser.PrintError('could not parse gen block!')
                    return None
                
                clip.subClips.append(subclip)
            else: # global cut
                # must have a input file
                if not clip.inFile:
                    parser.PrintError('no input file specified!')
                    return None
                
                cut = parser.ParseCut(parser.currLine)
                if cut is None:
                    parser.PrintError('could not parse cut statement!')
                    return None
                
                subclip = ClipData(clip.inFile,cut[0],cut[1],autofade=clip.autoFade,lineNum=parser.lineNum)
                subclip.format = clip.format
                clip.subClips.append(subclip)
                
            clip.start = 0.0
            if clip.end is None:
                clip.end = 0.0
            clip.end += subclip.GetLength()
            
            # finish xfade
            if pendingXFadeClip is not None:
                sub = clip.subClips.pop()
                pendingXFadeClip.subClips.append(sub)
                # crossfading uses up some clip length
                clip.end -= pendingXFadeClip.xfade.duration
                pendingXFadeClip.end += sub.GetLength()
                pendingXFadeClip.end -= pendingXFadeClip.xfade.duration
                pendingXFadeClip.subClipsHash = pendingXFadeClip.GetSubClipsHash()
                clip.subClips.append(pendingXFadeClip)
                pendingXFadeClip = None
        elif parser.currLine.startswith('volume '):
            clip.volume = parser.ParseVolume(parser.currLine)
            if clip.volume is None:
                parser.PrintError('could not parse volume!')
                return None
        elif parser.currLine.startswith('zoom '):
            if spec.width==0 or spec.height==0:
                parser.PrintError('must specify input video before zoom!')
                return None
                
            clip.scale = parser.ParseZoom(parser.currLine,spec.width,spec.height)
            if clip.scale is None:
                parser.PrintError('could not parse zoom!')
                return None
        elif parser.currLine.startswith('fade '):
            if top:
                parser.PrintError('cannot fade in global scope!')
                return None
                
            newFadeData = parser.ParseFadeStmt(parser.currLine)
            if newFadeData is None:
                parser.PrintError('could not parse fade statement!')
                return None
            
            if newFadeData.inLen!=FADE_NOT_SET:
                clip.fadeData.inLen = newFadeData.inLen
            if newFadeData.outLen!=FADE_NOT_SET:
                clip.fadeData.outLen = newFadeData.outLen
        elif parser.currLine.startswith('xfade '):
            xFadeData = parser.ParseXFadeStmt(parser.currLine)
            if xFadeData is None:
                parser.PrintError('could not parse xfade statement!')
                return None
            
            if pendingXFadeClip is not None:
                parser.PrintError('expected a clip before another xfade!')
                return None
            
            if not clip.subClips:
                parser.PrintError('must have a clip before xfade!')
                return None
            
            pendingXFadeClip = ClipData(clip.inFile,0.0,0.0)
            pendingXFadeClip.xfade = xFadeData
            pendingXFadeClip.format = clip.format
            sub = clip.subClips.pop()
            pendingXFadeClip.subClips.append(sub)
            pendingXFadeClip.end = sub.GetLength()
        elif parser.currLine.startswith('text '):
            startLine = parser.lineNum
            text = ParseTextBlock(parser,spec)
            
            if text is None:
                parser.lineNum = startLine
                parser.PrintError(f'could not parse text! (syntax: text fontDef x y "text" [color]')
                return None
                
            clip.texts.append(text)
        elif parser.currLine.startswith('cut ') and not top:
            if not clip.inFile:
                parser.PrintError('no input file specified!')
                return None
            
            if clip.start is not None and clip.end is not None:
                parser.PrintError('multiple cut statements found in one clip!')
                return None
            
            cut = parser.ParseCut(parser.currLine)
            if cut is None:
                parser.PrintError('could not parse cut statement!')
                return None
                
            clip.start = cut[0]
            clip.end = cut[1]
        elif parser.currLine == 'end':
            if top:
                parser.PrintError('unexpected keyword \'end\'')
                return None
            break
        else:
            parser.PrintError(f'unexpected line \'{parser.currLine}\'')
            return None
            
    if clip.start is None or clip.end is None:
        parser.PrintError(f'expected a clip start and end!')
        return None
        
    if pendingXFadeClip is not None:
        parser.PrintError(f'expected clip after xfade statement!')
        return None
    
    for text in clip.texts:
        # fix text timestamps if none were provided
        if text.start is None:
            text.start = clip.start
        if text.end is None:
            text.end = clip.end
    for audio in clip.audios:
        if audio.end==END_TIME_POS:
            audio.end = clip.end-clip.start+audio.start
    
    if top:
        print(f'Total length: {GetTimeString(round(clip.end-clip.start,3))}')
    
    clip.ComputeHashes()
    return clip
    

def ParseClipFile(path):
    spec = ClipSpec()
    
    currInFile = ''
    with open(path,'r') as f:
        parser = ClipParser(f)
        
        masterClip = ParseClip(parser,spec,currInFile,DEFAULT_AUTOFADE,True)
        spec.clip = masterClip
        
    if spec.outFile=='':
        parser.PrintError('no output file specified!')
        return None
    
    return spec
    
def ConcatClips(clip):
    VerbosePrint('tmpcliplist:')
    clipListPath = os.path.join(clipDir,clipListName)
    with open(clipListPath,'w') as clipListFile:
        for subclip in clip.subClips:
            name = subclip.GetName()
            text = f"file '{name}'\n"
            VerbosePrint(text,end='')
            clipListFile.write(text)
    
    # joiner clip
    outName = os.path.join(clipDir,'tmp'+clip.GetName())
        
    ccCmdArgs = [ffmpegPath,'-loglevel','warning','-safe','0','-y','-f','concat','-i',clipListPath,'-c','copy',outName]
    print('Concatenating...')
    VerbosePrint(' '.join(ccCmdArgs))
    res = subprocess.run(ccCmdArgs)
    
    if os.path.isfile(clipListPath):
        os.remove(clipListPath)
        
    if res.returncode!=0:
        print(f'concat error: ffmpeg exited with code {res.returncode}')
        return False
        
    return True
    
def MakeGenClip(spec,clip,i,total):
    outName = ''
    if spec.clip is clip:
        outName = spec.outFile
    cmd = GenerateGenCmd(spec,clip,outName)
    print(f'Generating... ({i+1}/{total})')
    clip.GenerateTextFiles()
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    clip.CleanTextFiles()
    
    if res.returncode!=0:
        print(f'clipping error: ffmpeg exited with code {res.returncode}')
        return False
    
    return True

def MixInAudios(spec,clip):
    audioFilter = clip.GetAudioFilterString()
    if spec.clip is clip:
        basename = os.path.basename(spec.outFile)
        inFile = os.path.join(clipDir,'unmixed'+basename)
        outFile = spec.outFile
    else:
        inFile = os.path.join(clipDir,'unmixed'+clip.GetName())
        outFile = os.path.join(clipDir,clip.GetName())
    
    cmd = [ffmpegPath,'-y','-loglevel','warning','-i',inFile]
    
    for audio in clip.audios:
        cmd.append('-i')
        cmd.append(audio.inFile)
    cmd.append('-filter_complex')
    cmd.append(audioFilter)
    cmd.append('-c:v')
    cmd.append('copy')
    cmd.append('-map')
    cmd.append('[out]')
    cmd.append('-map')
    cmd.append('0:v')
    cmd.append(outFile)
    print('Mixing...')
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    os.remove(inFile)
    if res.returncode!=0:
        print(f'mixing error: ffmpeg exited with code {res.returncode}')
        return False
        
    if clip is not spec.clip:
        print('Reencoding...')
        if not ReencodeVideo(os.path.basename(outFile)):
            print(f'reencode error: ffmpeg could not reencode!')
            return False
    return True
    

def ZoomVideo(spec,clip,name):
    # crop
    path = os.path.join(clipDir,name)
    newPath = os.path.join(clipDir,'tmpcrop'+name)
    
    cmd = [ffmpegPath,'-y','-loglevel','warning','-i',path,
        '-vf',f'crop=w={clip.scale.w}:h={clip.scale.h}:x={clip.scale.x}:y={clip.scale.y}',
        '-c:a','copy',newPath
    ]
    print('Cropping...')
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    if res.returncode!=0:
        os.remove(newPath)
        print(f'cropping error: ffmpeg exited with code {res.returncode}')
        return False
    
    os.replace(newPath,path)
    
    # scale
    newPath = os.path.join(clipDir,'tmpscale'+name)
    cmd = [ffmpegPath,'-y','-loglevel','warning','-i',path,
        '-vf',f'scale=w={spec.width}:h={spec.height}:flags=lanczos',
        '-c:a','copy',
        newPath
    ]
    print('Scaling...')
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    if res.returncode!=0:
        os.remove(newPath)
        print(f'scaling error: ffmpeg exited with code {res.returncode}')
        return False
    
    os.replace(newPath,path)
    return True


def MakeClip(spec,clip,i,total):
    if type(clip) is GenData:
        return MakeGenClip(spec,clip,i,total)

    assert clip.subClips is not None
    # if a clip has subclips, then its inFile is a concat of its rendered subclips
    earlyJoin = (len(clip.subClips)>1 and clip.xfade is None) or spec.clip is clip
    if earlyJoin:
        # now concat
        if not ConcatClips(clip):
            return False
    #else:
        #if not os.path.isfile(clip.inFile):
        #    print(f"Input video from line {clip.lineNum} named '{clip.inFile}' does not exist!")
        #    return False
    
    outName = ''
    if spec.clip is clip:
        outName = spec.outFile
    cmd = GenerateCmd(spec,clip,outName)
    
    if clip.xfade:
        print(f'Fading... ({i+1}/{total})')
    else:
        print(f'Clipping... ({i+1}/{total})')
        
    clip.GenerateTextFiles()
    VerbosePrint(' '.join(cmd))
    res = subprocess.run(cmd)
    clip.CleanTextFiles()
    
    if earlyJoin:
        tmpName = os.path.join(clipDir,'tmp'+clip.GetName())
        VerbosePrint(f'cleaning up {tmpName}...')
        os.remove(tmpName)
    
    if res.returncode!=0:
        print(f'clipping error: ffmpeg exited with code {res.returncode}')
        return False
        
    if clip.scale.w!=0 and clip.scale.h!=0:
        if spec.clip is clip:
            name = spec.outFile
        else:
            name = clip.GetName()
        if not ZoomVideo(spec,clip,name):
            return False
        
    if clip.audios:
        return MixInAudios(spec,clip)
    
    return True


def GetClipTree(clip,l=None):
    if l is None:
        l = []
    
    if type(clip) is ClipData:
        for subclip in clip.subClips:
            GetClipTree(subclip,l)
    l.append(clip)
    
    return l

def LoadClipDB():
    files = os.listdir(clipDir)
    return files

def main(clipFilePath):
    try:
        res = subprocess.run([ffmpegPath,'-version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if res.returncode!=0:
            raise FileNotFoundError
    except FileNotFoundError:
        print('Could not find ffmpeg!')
        return

    if not os.path.isfile(clipFilePath):
        print(f"Path '{clipFilePath}' does not exist!")
        return
        
    clipSpec = ParseClipFile(clipFilePath)
    if clipSpec is None or clipSpec.clip is None:
        return
    
    if not os.path.isdir(clipDir):
        os.mkdir(clipDir)
        
    if len(clipSpec.clip.subClips)==0:
        return
        
    for path in os.listdir(clipDir):
        p = os.path.join(clipDir,path)
        if os.stat(p).st_size==0:
            os.remove(p)
            VerbosePrint(f'removed zero-byte file {p}')
    
    currClips = LoadClipDB()
    
    toMakeClips = GetClipTree(clipSpec.clip)
    # remove the master clip
    toMakeClips.remove(clipSpec.clip)
    
    if currClips:
        wantSet = set(toMakeClips)
        currSet = set(currClips)
        
        # consists of elements from currSet
        toDelete = currSet.difference(wantSet)
        VerbosePrint(f'deleting: {toDelete}')
        
        # delete all removed clips
        for delClip in toDelete:
            name = delClip
            path = os.path.join(clipDir,name)
            if os.path.isfile(path):
                VerbosePrint(f'deleting clip: {path}')
                os.remove(path)
        
        # consists of elements from wantSet
        toCreate = wantSet.difference(currSet)
        VerbosePrint(f'creating: {toCreate}')
        newList = []
        for clip in toMakeClips:
            if clip in toCreate:
                newList.append(clip)
        
        toMakeClips = newList
    
    l = len(toMakeClips)
    for i,clip in enumerate(toMakeClips):
        if not MakeClip(clipSpec,clip,i,l):
            return
    
    if not MakeClip(clipSpec,clipSpec.clip,0,1):
        return

    print('Success!')
    print(f'Output saved to {clipSpec.outFile}')
    
    
if __name__=='__main__':
    parser = argparse.ArgumentParser(
                    prog='clipper',
                    description='Cuts clips out of a video')
    parser.add_argument('clipfile',help='a clipperfile specifying input video and clips')
    parser.add_argument('-v','--verbose',help='verbose logging for debugging',action='store_true')
    parser.add_argument('--version',help='print version and exit',action='version',version='clipper 0.0.1')
    
    args = parser.parse_args()
    
    if args.verbose:
        verbose = True
    
    baseDir = os.path.dirname(args.clipfile)
    clipDir = os.path.join(baseDir,'clips')
    startTime = time.perf_counter()
    main(args.clipfile)
    totalTime = time.perf_counter()-startTime
    print(f'Done in {round(totalTime,3)}s')
    input()