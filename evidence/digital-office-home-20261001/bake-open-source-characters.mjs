import fs from 'node:fs'
import path from 'node:path'
import { createCanvas, loadImage } from '@napi-rs/canvas'
import {
  AnimationState, AnimationStateData, AtlasAttachmentLoader, CanvasTexture,
  Physics, Skeleton, SkeletonJson, SkeletonRenderer, TextureAtlas, Vector2,
} from '@esotericsoftware/spine-canvas'

/**
 * 离线烘焙 workbzw/ai-office-react 原生 Chibi Stickers 人物。
 * 来源提交：72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96
 * 不向 Astra 应用添加运行时依赖；本脚本应复制到独立临时目录执行。
 * 临时依赖：@esotericsoftware/spine-canvas@4.2.120、@napi-rs/canvas。
 * 使用：node render.mjs <原public/assets/characters/chibi-stickers目录> <输出目录>
 * 原目录包含 chibi-stickers.json、.atlas 和 atlas 引用的10张PNG。
 */
const [sourceArgument, outputArgument] = process.argv.slice(2)
if (!sourceArgument || !outputArgument) {
  console.error('Usage: node render.mjs <source-character-directory> <output-directory>')
  process.exit(1)
}
const source = path.resolve(sourceArgument)
const output = path.resolve(outputArgument)
fs.mkdirSync(output, { recursive: true })
const atlas = new TextureAtlas(fs.readFileSync(path.join(source, 'chibi-stickers.atlas'), 'utf8'))
for (const page of atlas.pages) {
  const image = await loadImage(path.join(source, page.name))
  const canvas = createCanvas(image.width, image.height)
  const context = canvas.getContext('2d')
  context.drawImage(image, 0, 0)
  // The source atlas is premultiplied; Canvas compositing expects straight alpha.
  if (page.pma) {
    const pixels = context.getImageData(0, 0, image.width, image.height)
    for (let i = 0; i < pixels.data.length; i += 4) {
      const alpha = pixels.data[i + 3]
      if (!alpha || alpha === 255) continue
      for (let channel = 0; channel < 3; channel++) pixels.data[i + channel] = Math.min(255, Math.round(pixels.data[i + channel] * 255 / alpha))
    }
    context.putImageData(pixels, 0, 0)
  }
  page.setTexture(new CanvasTexture(canvas))
}
const json = new SkeletonJson(new AtlasAttachmentLoader(atlas))
const data = json.readSkeletonData(JSON.parse(fs.readFileSync(path.join(source, 'chibi-stickers.json'), 'utf8')))
const skins = ['misaki', 'erikari', 'nate', 'harri', 'luke', 'soeren', 'mario', 'sinisa', 'spineboy']
const poses = []
for (const [index, skin] of skins.entries()) {
  for (const facing of ['front', 'back']) {
    const skeleton = new Skeleton(data)
    skeleton.setSkinByName(skin)
    skeleton.setToSetupPose()
    const animation = new AnimationState(new AnimationStateData(data))
    animation.setAnimation(0, `movement/idle-${facing}`, true)
    animation.update(.15)
    animation.apply(skeleton)
    skeleton.updateWorldTransform(Physics.reset)
    const offset = new Vector2(), size = new Vector2()
    skeleton.getBounds(offset, size)
    poses.push({ index, skin, facing, skeleton, bounds: { x: offset.x, y: offset.y, width: size.x, height: size.y } })
  }
}
// Every skin and facing shares one canvas, scale and foot baseline.
const width = 256, height = 320, baseline = 300
const maxHalfWidth = Math.max(...poses.map(p => Math.max(Math.abs(p.bounds.x), Math.abs(p.bounds.x + p.bounds.width))))
const maxTop = Math.max(...poses.map(p => p.bounds.y + p.bounds.height))
const minBottom = Math.min(...poses.map(p => p.bounds.y))
const scale = Math.min((width - 24) / (2 * maxHalfWidth), (baseline - 12) / maxTop, (height - baseline - 4) / -Math.min(-.001, minBottom))
const manifest = { source: 'workbzw/ai-office-react', commit: '72f2ee59ea8e1fa7d94b222c0efc5bb857a2bc96', width, height, baseline, scale, skins, characters: [] }
for (const pose of poses) {
  const resolution = 4
  const canvas = createCanvas(width * resolution, height * resolution)
  const context = canvas.getContext('2d')
  context.imageSmoothingEnabled = true
  context.scale(resolution, resolution)
  context.translate(width / 2, baseline)
  context.scale(scale, -scale)
  const renderer = new SkeletonRenderer(context)
  renderer.triangleRendering = true
  renderer.draw(pose.skeleton)
  const exported = createCanvas(width, height)
  const exportContext = exported.getContext('2d')
  exportContext.imageSmoothingEnabled = true
  exportContext.imageSmoothingQuality = 'high'
  exportContext.drawImage(canvas, 0, 0, width, height)
  const filename = `character-${pose.index}-${pose.facing}.png`
  fs.writeFileSync(path.join(output, filename), exported.toBuffer('image/png'))
  const pixels = exportContext.getImageData(0, 0, width, height)
  let minX = width, minY = height, maxX = -1, maxY = -1
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (pixels.data[(y * width + x) * 4 + 3] < 10) continue
    minX = Math.min(minX, x); maxX = Math.max(maxX, x)
    minY = Math.min(minY, y); maxY = Math.max(maxY, y)
  }
  manifest.characters.push({ index: pose.index, skin: pose.skin, facing: pose.facing, filename, bounds: [minX, minY, maxX, maxY] })
  console.log(filename, 'visible bounds', [minX, minY, maxX, maxY].join(','))
}
fs.writeFileSync(path.join(output, 'manifest.json'), JSON.stringify(manifest, null, 2))
console.log('Fixed canvas', width, height, 'baseline', baseline, 'scale', scale)
