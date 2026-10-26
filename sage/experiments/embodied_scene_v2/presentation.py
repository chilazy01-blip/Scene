"""Decode-validated portable HD delivery from exact rendered chunks."""
from pathlib import Path
import base64,csv,html,json,shutil,subprocess,zipfile
import numpy as np
from PIL import Image,ImageDraw
import imageio.v2 as imageio
import imageio_ffmpeg
from sage.experiments.embodied_scene_v1.package import bound
from .config import ROOT,write_json

def merge(output_root=None, selected_chunks=None):
    directory=(Path(output_root) if output_root is not None else ROOT)/'presentation';media=directory/'media';media.mkdir(exist_ok=True);summaries=[]
    for kind in ['navigate','pick_place','grasp_closeup']:
        chunks=([Path(p) for p in selected_chunks[kind]] if selected_chunks is not None
                else sorted((directory/'chunks').glob(kind+'_*')));frames=[];manifests=[]
        for chunk in chunks:
            manifest=json.loads((chunk/'manifest.json').read_text());frames+=manifest['frames'];manifests.append(manifest)
        assert frames and [f['frame'] for f in frames]==list(range(len(frames)))
        assert len({f['state_index'] for f in frames})==len(frames)
        assert all(m['width']==1440 and m['height']==1080 and m['fps']==25 and m['crf']==16 for m in manifests)
        assert len({m['source_trajectory']['sha256'] for m in manifests})==1
        listing=media/(kind+'_concat.txt');listing.write_text(''.join("file '"+str(c/'chunk.mp4')+"'\n" for c in chunks))
        video=media/(kind+'.mp4')
        if video.exists():raise ValueError('Video already exists; verify rather than overwrite')
        cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(video)]
        subprocess.run(cmd,check=True)
        reader=imageio.get_reader(video);meta=reader.get_meta_data();count=0
        for frame in reader:
            if frame.shape!=(1080,1440,3):raise ValueError('Native size mismatch')
            count+=1
        reader.close();assert count==len(frames) and abs(meta['duration']-count/25)<.041
        assert abs(count/25-(frames[-1]['time']-frames[0]['time']))<=.04001
        if kind=='grasp_closeup':assert count/25<=12.0001
        row=dict(kind=kind,video=bound(video),native_size=[1440,1080],fps=25,frames=count,duration_s=count/25,all_frames_decoded=True,no_reencode_merge=True,
            source_trajectory=manifests[0]['source_trajectory'],source_model=manifests[0]['source_model'],frames_manifest=frames,chunks=[bound(c/'manifest.json') for c in chunks])
        write_json(media/(kind+'_manifest.json'),row);summaries.append(row)
        pngs=[p for chunk in chunks for p in sorted(chunk.glob('frame_*.png'))]
        chosen=np.linspace(0,len(pngs)-1,min(6,len(pngs))).round().astype(int)
        sheet=Image.new('RGB',(1440,2*390),'#f3f4f6');draw=ImageDraw.Draw(sheet)
        for i,n in enumerate(chosen):
            im=Image.open(pngs[n]);im.thumbnail((480,360),Image.Resampling.LANCZOS);x=(i%3)*480;y=(i//3)*390;sheet.paste(im,(x,y))
            frame_index=int(pngs[n].stem.split('_')[-1]);draw.text((x+10,y+365),f'{kind} | {frames[frame_index]["time"]:.2f}s',fill='black')
        sheet.save(media/(kind+'_sheet.jpg'),quality=94)
        shutil.copy2(pngs[len(pngs)//2],media/(kind+'_poster.png'))
    write_json(directory/'VIDEO_VERIFICATION.json',dict(videos=summaries,real_browser_playback_tested=False))
    print('Three native videos fully decoded and verified',flush=True)

def site():
    directory=ROOT/'presentation';media=directory/'media';verification=json.loads((directory/'VIDEO_VERIFICATION.json').read_text());videos=verification['videos']
    if (ROOT/'REPORT.md').exists():shutil.copy2(ROOT/'REPORT.md',directory/'REPORT.md')
    def make(embedded):
        cards=[]
        names={'navigate':'完整导航','pick_place':'完整抓放','grasp_closeup':'夹爪接触近景'}
        for v in videos:
            kind=v['kind'];source=('data:video/mp4;base64,'+base64.b64encode((media/(kind+'.mp4')).read_bytes()).decode()) if embedded else 'media/'+kind+'.mp4'
            download_source=source if embedded else 'data:video/mp4;base64,'+base64.b64encode((media/(kind+'.mp4')).read_bytes()).decode()
            poster=('data:image/png;base64,'+base64.b64encode((media/(kind+'_poster.png')).read_bytes()).decode()) if embedded else 'media/'+kind+'_poster.png'
            cards.append(f'<section><h2>{names[kind]}</h2><p>原生 1440 × 1080 · 25 fps · {v["duration_s"]:.2f} 秒 · 真实保存状态回放</p><video controls preload="metadata" poster="{poster}"><source src="{source}" type="video/mp4"></video><p><a download="{kind}.mp4" href="{download_source}">下载 MP4</a> · 播放器右下角可全屏</p></section>')
        for path in sorted((directory/'round2_evidence').glob('pair*_sheet.jpg')):
            source=('data:image/jpeg;base64,'+base64.b64encode(path.read_bytes()).decode()) if embedded else str(path.relative_to(directory))
            pairs=json.loads((directory/'round2_evidence/PAIRS.json').read_text());pair=pairs[int(path.stem.split('_')[0][4:])]
            before=json.loads((Path(pair['before'])/'result.json').read_text());after=json.loads((Path(pair['after'])/'result.json').read_text())
            description=f"{pair['label']} · {pair['split']} · {pair['method']} · {'通过' if before['success'] else '失败'} → {'通过' if after['success'] else '失败'}"
            cards.append(f'<section><h2>第二轮诊断对照</h2><p>{html.escape(description)}</p><p>上排为原条件，下排为对应候选。画面取自实际轨迹；I0候选搜索画面不等同于未见初始化上的收益，具体结论以实验报告为准。</p><img style="width:100%;height:auto" src="{source}" alt="第二轮对应时刻真实轨迹对照"></section>')
        impact=directory/'legacy_impact'
        if impact.exists():
            path=impact/'002_books.png';source=('data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()) if embedded else str(path.relative_to(directory))
            cards.append(f'<section><h2>旧五书冲击诊断</h2><p>最坏条件的真实落地时刻：代理接触穿透约7.54mm。图像按已保存姿态回放，不能用单幅渲染替代精确网格穿透测量。</p><img style="width:100%;height:auto" src="{source}" alt="书本与地板实际冲击位置"></section>')
        return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>卧室具身仿真 · 第二轮高清展示</title><style>body{font:17px/1.7 system-ui,sans-serif;background:#edf1f5;color:#1d2938;margin:0}main{max-width:1160px;margin:auto;padding:32px 20px}h1{font-size:30px;line-height:1.3}section{background:white;border-radius:14px;padding:22px;margin:24px 0;box-shadow:0 4px 24px #2030400a}video{display:block;width:100%;height:auto;background:#111;border-radius:8px}a{color:#175b9f}p{margin:10px 0}small{color:#516273}</style><main><h1>卧室具身仿真 · 第二轮高清展示</h1><p>完整导航、抓放与关键接触近景。视频采用第一阶段真实轨迹重新渲染，原生高清，动作未经插值。</p>'''+('' if embedded else '<p><a href="standalone.html" download>下载单文件离线 HTML</a> · <a href="embodied_round2_hd.zip" download>下载完整展示包</a> · <a href="REPORT.md">实验报告</a></p>')+''.join(cards)+'''<section><h2>证据与范围</h2><p>MuJoCo 原生渲染，恢复源基础颜色纹理，保留已有资产表面瑕疵；完整 PBR 法线与粗糙度效果尚未复现。机器人使用真值状态控制，物性为声明先验。</p><p>第二轮结果分开报告任务完成、禁止接触、工程检查和场景覆盖率。同一卧室的布局变体不代表跨房间泛化。</p><small>离线文件不需要外部网络或 JavaScript。已完成全片解码与时间/轨迹绑定检查；真实浏览器播放与用户画质满意度单列。</small></section></main></html>'''
    (directory/'index.html').write_text(make(False));(directory/'standalone.html').write_text(make(True))
    deliver=[directory/'index.html',directory/'standalone.html',directory/'VIDEO_VERIFICATION.json',directory/'HD_PROFILE_FROZEN.json',*media.glob('*')]
    if (directory/'REPORT.md').exists():deliver.append(directory/'REPORT.md')
    for sub in ['comparisons','round2_evidence','legacy_impact']:
        if (directory/sub).exists():deliver.extend(p for p in (directory/sub).rglob('*') if p.is_file())
    archive=directory/'embodied_round2_hd.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for path in deliver:z.write(path,path.relative_to(directory))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    write_json(directory/'PORTABLE_VERIFICATION.json',dict(standalone=bound(directory/'standalone.html'),archive=bound(archive),embedded_videos=[v['video'] for v in videos],external_dependencies=False,archive_complete_viewer_assets=True,simulation_models_excluded_from_viewer_archive=True,real_browser_playback_tested=False))
    print('Portable HD presentation built',flush=True)
