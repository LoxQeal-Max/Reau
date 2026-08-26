import uiautomator2 as u2
import re

d = u2.connect()
xml = d.dump_hierarchy()

texts = re.findall(r'text="([^"]+)"', xml)
rids = re.findall(r'resource-id="([^"]+)"', xml)
clsses = re.findall(r'class="([^"]+)"', xml)

print('UI 树 XML 长度:', len(xml))
print('text 元素:', [t for t in texts if t.strip()][:20])
print('resource-id 元素 (去重):', list(set(rids))[:20])
print('class 元素 (去重):', list(set(clsses))[:10])
print()
print('屏幕:', d.info.get('displayWidth'), 'x', d.info.get('displayHeight'))
print('前台 app:', d.info.get('currentPackageName'))
