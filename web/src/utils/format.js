// 展示层的小工具：日期、异常标记、证型配色。

export function shortDate(iso) {
  if (!iso) return '—'
  return String(iso).slice(0, 10)
}

export function shortTime(iso) {
  if (!iso) return '—'
  return String(iso).replace('T', ' ').slice(0, 16)
}

export const FLAG_TEXT = { H: '偏高', L: '偏低', N: '正常' }
export const FLAG_CLASS = { H: 'badge-danger', L: 'badge-warn', N: 'badge-ok' }

// 八证型固定配色，雷达图与标签共用，避免同一证型在不同页面颜色不一致
export const SYNDROME_COLORS = {
  肝郁: '#3A7359', 脾虚: '#B8912F', 痰湿: '#37699B', 湿热: '#C0483D',
  阴虚: '#8C5AA6', 阳虚: '#C8862A', 气血两虚: '#A0563E', 血瘀: '#5C6B63',
}

export function severityClass(level) {
  return { high: 'badge-danger', watch: 'badge-warn', info: 'badge-info' }[level] || 'badge-quiet'
}

export function severityText(level) {
  return { high: '建议就医评估', watch: '关注', info: '提示' }[level] || level || '提示'
}

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.readAsDataURL(file)
  })
}

// 大图先压到长边 1280，减少上传体积与后端解码时间
export function compressImage(dataUrl, maxSide = 1280, quality = 0.9) {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
      if (scale === 1) return resolve(dataUrl)
      const c = document.createElement('canvas')
      c.width = Math.round(img.width * scale)
      c.height = Math.round(img.height * scale)
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height)
      resolve(c.toDataURL('image/jpeg', quality))
    }
    img.onerror = () => resolve(dataUrl)
    img.src = dataUrl
  })
}
