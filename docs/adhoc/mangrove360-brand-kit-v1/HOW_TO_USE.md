# Mangrove 360 — วิธีใช้ชุดภาพและหน้าเข้าสู่ระบบ

Version 1 · Created 23 October 2026 · ภาษาไทย / English implementation examples

## เริ่มใช้งาน

1. แตกไฟล์ ZIP โดยเก็บโครงสร้างโฟลเดอร์ไว้ครบ
2. เปิด `index.html` เพื่อดูภาพทั้งหมด หรือเปิด `login.html` เพื่อดูหน้าเข้าสู่ระบบ
3. เปิด `dashboard.html` เพื่อดูตัวอย่างการใช้ภาพในหน้าแดชบอร์ด
4. คัดลอกภาพจาก `assets/` ไปยังโปรเจกต์เว็บของคุณ และปรับเส้นทางไฟล์ให้ตรงกัน

ตัวอย่างทั้งสามหน้าเปิดในเบราว์เซอร์ได้โดยตรง ไม่ต้องติดตั้งโปรแกรมเสริม ไม่ใช้ CDN และไม่ดาวน์โหลดฟอนต์จากอินเทอร์เน็ต มีภาพหน้าจอพร้อมใช้ใน `previews/` ด้วย

**หน้าเข้าสู่ระบบเป็นงานออกแบบตัวอย่าง** ปุ่ม Show/Hide, การตรวจรูปแบบอีเมล, ข้อความตอบกลับของปุ่ม Sign in และการเลือกพื้นที่ในแดชบอร์ดใช้งานได้ แต่ยังไม่เชื่อมระบบบัญชีผู้ใช้ ระบบวิเคราะห์ หรือฐานข้อมูล ไม่มีการส่ง เก็บ หรือบันทึกรหัสผ่านจากตัวอย่างนี้ จึงควรใช้ข้อมูลทดสอบเท่านั้น

## ไฟล์ที่ให้มา

| ไฟล์ | ใช้ที่ไหน | แนวทาง |
| --- | --- | --- |
| `assets/logo-primary.png` | โลโก้หลัก หน้าเข้าสู่ระบบ เมนูบนเว็บ หัวรายงาน | พื้นหลังโปร่งใส เหมาะกับพื้นสีขาวหรือสีทราย |
| `assets/logo-symbol.png` | สัญลักษณ์แอป พื้นที่แคบ ไอคอนเบราว์เซอร์ | พื้นหลังโปร่งใส ใช้แทนโลโก้เต็มเมื่อพื้นที่ไม่พอ |
| `assets/login-hero.png` | ภาพข้างฟอร์มเข้าสู่ระบบ หน้าเริ่มต้น | ภาพป่าชายเลนและร่องน้ำที่สร้างด้วย AI ไม่มีตัวหนังสือฝังในภาพ |
| `assets/dashboard-banner.png` | แบนเนอร์ต้อนรับ Onboarding หัวส่วนเนื้อหา | ภาพประกอบแนวนอน ไม่ใช่แผนที่ |
| `assets/empty-state.png` | ยังไม่เลือก AOI / ยังไม่มีรายงาน | ภาพประกอบพื้นหลังโปร่งใส ใช้พร้อมข้อความบอกขั้นตอนถัดไป |
| `login.html` | ตัวอย่างหน้าเข้าสู่ระบบ | รองรับคอมพิวเตอร์และมือถือ |
| `dashboard.html` | ตัวอย่างหน้าแดชบอร์ด | เลือก South Sumatra หรือ Lamu เพื่อเปลี่ยนสถานะตัวอย่างได้ |
| `index.html` | หน้ารวมชุดภาพ | เปิดดูและดาวน์โหลดไฟล์ภาพแต่ละรายการ |
| `tokens.css` | สี ฟอนต์ และตัวแปรพื้นฐาน | ใช้ร่วมกันทุกหน้า |
| `styles.css` | รูปแบบหน้าตัวอย่าง | แก้ขนาด ระยะห่าง และ responsive layout ที่นี่ |
| `asset-manifest.json` | ขนาดภาพ ความโปร่งใส และ SHA-256 | ใช้ตรวจว่าไฟล์ที่ส่งต่อเป็นชุดเดียวกัน |
| `GENERATION_PROMPTS.json` | คำสั่งสร้างภาพฉบับเต็ม | บันทึกที่มาของการออกแบบและใช้สร้างเวอร์ชันใหม่ |

ขนาดพิกเซลจริงอยู่ใน `asset-manifest.json` ไม่ใช่ขนาดที่ต้องบังคับแสดงบนหน้าเว็บ ภาพหน้าจอใน `previews/` เป็นภาพตัวอย่าง UI ไม่ใช่ภาพที่นำไปแทนฟอร์มจริง

## แนวคิดงานออกแบบ

ต้นโกงกาง รากค้ำจุน และเส้นโอบรอบสื่อถึงการมองพื้นที่ชายฝั่งอย่างรอบด้าน ภาพหลักใช้ป่าชายเลนและน้ำทะเล ส่วนภาพประกอบใช้สีอ่อนเพื่อให้เนื้อหาและข้อมูลเด่นกว่าฉากหลัง

ใช้ภาษาเรียบง่ายกับผู้พัฒนาโครงการ ชุมชน และหน่วยงานท้องถิ่น โลโก้และภาพประกอบไม่ได้แสดงการรับรองโครงการ สิทธิการพัฒนา หรือการรับรองคาร์บอนเครดิต

### สีประจำชุด

| ชื่อ | Hex | การใช้งาน |
| --- | --- | --- |
| Forest | `#123F3A` | ปุ่มหลัก หัวข้อ พื้นเข้ม |
| Sea teal | `#297C78` | รายละเอียดรอง เส้นเน้น |
| Sage | `#A8BDA1` | พื้นอ่อนและภาพประกอบ |
| Sand | `#F5F3EB` | พื้นหลังหน้าเว็บและการ์ด |
| Muted gold | `#C6A465` | จุดเน้นขนาดเล็ก |
| Ink | `#173C38` | ข้อความหลัก |
| Muted text | `#526863` | ข้อความรองบนพื้นอ่อน |

Hex เหล่านี้เป็นสีที่กำหนดสำหรับ UI ภาพที่สร้างด้วย AI อาจมีเฉดสีและพื้นผิวแตกต่างเล็กน้อย ใช้ตัวแปรใน `tokens.css` เพื่อควบคุมสีของส่วนติดต่อผู้ใช้

ฟอนต์ใช้ `Inter, Segoe UI, Leelawadee UI, system-ui, sans-serif` โดยไม่มีไฟล์ฟอนต์แนบมา หากไม่ได้ติดตั้ง Inter เบราว์เซอร์จะใช้ตัวถัดไปในรายการ

## การวางโลโก้

- รักษาสัดส่วนเดิม ใช้ `object-fit: contain` และอย่ายืดหรือบีบภาพ
- แสดงโลโก้เต็มกว้างประมาณ 180–240 CSS px ในหน้าเข้าสู่ระบบ และ 150–190 px ในเมนูด้านข้าง
- เว้นพื้นที่รอบโลโก้อย่างน้อยประมาณครึ่งหนึ่งของความกว้างสัญลักษณ์ต้นไม้
- บนพื้นเข้ม ให้ใช้แผ่นรองสีขาวหรือสีทราย โลโก้ชุดนี้ไม่มีเวอร์ชันสีขาวที่อนุมัติแยกไว้
- สำหรับงานพิมพ์ขนาดใหญ่ ควรจัดทำต้นฉบับเวกเตอร์ก่อน ชุดนี้ส่งมอบโลโก้เป็น PNG โปร่งใส ไม่ได้อ้างว่าเป็นไฟล์ SVG หรือเวกเตอร์

```html
<img
  src="assets/logo-primary.png"
  alt="Mangrove 360"
  style="width:224px; height:auto;"
>
```

## ภาพหน้าเข้าสู่ระบบ

ภาพ `login-hero.png` แยกจากตัวหนังสือ ฟอร์ม และปุ่มทั้งหมด จึงแก้ข้อความหรือแปลภาษาได้โดยไม่ต้องสร้างภาพใหม่

ตัวอย่างที่ให้มาใช้ฟอร์มด้านซ้ายประมาณ 43% และภาพด้านขวาประมาณ 57% บนจอใหญ่ บนมือถือฟอร์มจะอยู่ก่อนภาพเพื่อให้ผู้ใช้เข้าสู่ระบบได้สะดวก

```css
.login-photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 62% center;
}
```

`cover` ครอปบางส่วนตามขนาดกรอบได้ หากต้องการเห็นภาพครบ ให้ใช้ `contain` แทนและยอมให้มีพื้นที่ว่างรอบภาพ เมื่อวางข้อความบนภาพ ให้เพิ่มแถบสีหรือไล่ความเข้มด้านหลังข้อความ และตรวจการอ่านได้ในทุกขนาดหน้าจอ

## การใช้ในเว็บทั่วไปหรือ React

สำหรับเว็บ HTML ให้เก็บ `assets/` ไว้ใกล้หน้าเว็บตามตัวอย่าง สำหรับ React สามารถวางภาพไว้ใน `public/assets/mangrove360/` แล้วอ้างด้วย URL ตามตัวอย่างนี้ โดยปรับ base path หากเว็บอยู่ใต้โฟลเดอร์ย่อย

```jsx
export function MangroveBrand() {
  return (
    <img
      src="/assets/mangrove360/logo-primary.png"
      alt="Mangrove 360"
      width="224"
      height="75"
      style={{ objectFit: "contain" }}
    />
  );
}
```

อย่าใช้ path จากเครื่องส่วนตัว เช่น `C:\\...` หรือ `D:\\...` ในเว็บที่เผยแพร่แล้ว ให้ใช้ URL ของไฟล์ที่เว็บเข้าถึงได้ ไฟล์ภาพ PNG ถูกเก็บเป็นต้นฉบับความละเอียดเต็ม สามารถทำสำเนา WebP สำหรับเว็บภายหลังได้ โดยตรวจว่าความโปร่งใสและรายละเอียดของโลโก้ยังถูกต้อง

## ใช้กับ Claude Artifact

1. แนบภาพที่ต้องการใช้ในบทสนทนาเดียวกับ Artifact พร้อมไฟล์คู่มือนี้
2. ระบุว่าไฟล์ไหนเป็นโลโก้ ภาพหน้าเข้าสู่ระบบ และภาพประกอบ อย่าให้ Claude สร้างโลโก้ทดแทนเอง
3. ให้ Claude ยืนยันว่าเข้าถึงภาพแต่ละไฟล์ได้ แล้วใช้วิธีอ้างไฟล์ที่สภาพแวดล้อมนั้นรองรับ หากไม่ได้ ให้เตรียม URL รูปภาพที่เว็บเข้าถึงได้หรือจัดไฟล์ให้เป็นโครงการเว็บก่อน
4. เส้นทาง `assets/...` ใน HTML ตัวอย่างจะใช้ได้ก็ต่อเมื่อไฟล์ถูกจัดไว้ตามโครงสร้างเดียวกัน การคัดลอก HTML อย่างเดียวไม่ได้คัดลอกภาพไปด้วย

### คำสั่งพร้อมใช้

```text
Use the attached Mangrove 360 brand assets to design a responsive login page
and a matching dashboard welcome state.

Use logo-primary.png as the main logo, login-hero.png as the login image,
dashboard-banner.png as the welcome banner, and empty-state.png when no
study area or assessment is selected. Use logo-symbol.png only where the
full wordmark would be too small.

Follow the colors and spacing guidance in HOW_TO_USE.md. Keep form fields,
buttons, and text as real accessible interface elements, not text baked
into an image. Preserve image aspect ratios and support mobile screens.

Confirm you can access each supplied image. If any image is inaccessible,
identify the missing file and explain the required asset connection;
do not silently replace it with unrelated imagery or a new logo.

The login is a design preview until connected to an authentication provider.
Do not collect real credentials, invent assessment figures, or present the
decorative imagery as a real map or a photograph of South Sumatra or Lamu.

Deliver runnable source files and describe any features that still need
a backend or live data connection.
```

## การเข้าถึงและการใช้ภาพอย่างถูกความหมาย

- ใช้ `alt="Mangrove 360"` สำหรับโลโก้ที่บอกชื่อผลิตภัณฑ์ หากโลโก้มีชื่อซ้ำกับข้อความข้างกันและเป็นเพียงภาพตกแต่ง ให้ใช้ `alt=""`
- ใช้ label ที่มองเห็นสำหรับช่องกรอกข้อมูล อย่าใช้ placeholder แทน label
- เก็บข้อความสำคัญไว้นอกภาพเพื่อให้โปรแกรมอ่านหน้าจอและการแปลภาษาใช้งานได้
- ภาพทั้งหมดสร้างขึ้นใหม่ด้วย built-in `image_gen` ภาพชายฝั่งเป็นภาพสมมติ ไม่ใช่ภาพถ่ายสำรวจหรือพื้นที่จริงใน South Sumatra หรือ Lamu
- อย่าใช้ภาพเหล่านี้เป็นหลักฐานขอบเขตที่ดิน สภาพป่าชายเลน ระดับน้ำ ภัยพิบัติ ROI หรือปริมาณคาร์บอนเครดิต

## เมื่อเชื่อมเป็นระบบใช้งานจริง

เชื่อมฟอร์มกับระบบบัญชีผู้ใช้ที่เลือก จัดการ session และ reset password ฝั่งระบบ และเก็บ secret/API keys ไว้ฝั่งเซิร์ฟเวอร์ เมนู Remember me ในตัวอย่างนี้เป็นเพียง UI ยังไม่มีผลต่อ session

เมื่อเปลี่ยน AOI ให้เชื่อมผลวิเคราะห์ของพื้นที่นั้นจริง ภาพชุดนี้ใช้ซ้ำได้ แต่ตัวเลข แผนที่ความเสี่ยง ข้อจำกัดสิทธิ และผลตอบแทนต้องเปลี่ยนตามข้อมูลของพื้นที่นั้น

## การตรวจรับชุดงาน

ตรวจเปิดหน้า gallery, login และ dashboard ทั้งจอใหญ่และมือถือ ตรวจภาพทุกไฟล์ว่าโหลดครบ ไม่มีการเลื่อนออกนอกจอ ทดลอง Show/Hide password, ปุ่ม reset แบบตัวอย่าง และการเปลี่ยนพื้นที่ ขนาดไฟล์ ความโปร่งใส และลายนิ้วมือ SHA-256 ตรวจย้อนกลับได้จาก `asset-manifest.json`

## English quick reference

Extract the complete ZIP, then open `index.html`. Use `login.html` and
`dashboard.html` as responsive design references. Copy the `assets/` folder
and update asset URLs to match your application's deployment path.

This package includes five original AI-generated raster assets, native
HTML/CSS page examples, PNG preview screenshots, generation prompts, and
an asset manifest. It does not contain working authentication, live maps,
geospatial analysis, or financial forecasts. Preserve the source PNGs and
do not use the conceptual imagery as evidence about a real coastal site.
