# Request to BMA: permission to use CCTV information in the GRP Bangkok flood pilot

**Date:** 3 October 2026
**From:** the SERVIR Global Risk Platform (GRP) pilot team, ADPC
**Status:** draft for the Product Owner to send. Nothing has been sent from GRP.

> **Update, 3 October 2026 (later).** BMA's flood site already publishes its camera list (camera
> ID, location, linked flood sensor and a live-view link) without a login. With the Product
> Owner's approval, the Gate A local demo now uses that list (ADR-0046). It shows each camera's
> location and sensor, and opens the live view on the provider's site in a new tab; GRP never
> embeds, relays, records or analyses video. **This request is therefore now mainly for
> permission and status:**
> - may GRP use the camera list and link to the live views (and on what terms, with what
>   attribution)?
> - may GRP show the live view inside its own page (embedding)?
> - how should GRP check whether a camera is working?
> - can BMA share which way each camera faces?

> **Update, 3 October 2026 (evening): bmatraffic.com.** BMA's traffic CCTV site
> (www.bmatraffic.com) shows a camera only to a visitor with a session on its own site, so its
> player cannot show inside another site's page. For the **local demo only**, GRP now opens one
> visitor session and passes on pictures (ADR-0051):
>
> - about one picture a second, only while an officer is watching, shared by all viewers;
> - never stored or analysed, and stopped after 10 minutes unless the officer continues.
>
> It is switched off everywhere else. **One more question for BMA:** may GRP pass on
> bmatraffic.com pictures like this beyond the local demo? If so, is there a preferred way,
> such as a snapshot address that does not need a session, an HTTPS address, or a limit on how
> often GRP should ask?

> **Update, 4 October 2026: an automatic water check (planned, not built).** The pilot now
> covers the whole of Bangkok. The Product Owner would like a simple automatic check on camera
> pictures near reported flooding: one word, **water**, **partial water** or **dry**. Its rules:
>
> - at most two cameras per active incident, every 15 minutes, with no picture stored (only the
>   word, the time and a fingerprint of the picture);
> - it never replaces an officer's check.
>
> This would change the earlier promise that pictures are never analysed, so **GRP asks first**.
> May GRP run this check on bmatraffic.com pictures? May the one-word result, without pictures,
> camera links or camera IDs, be shared in a public flood feed?

## Thai version (ฉบับภาษาไทย)

เรียน สำนักการระบายน้ำ กรุงเทพมหานคร

ทีมนำร่อง SERVIR Global Risk Platform (GRP) ของ ADPC กำลังทดลองหน้าจอสำหรับเจ้าหน้าที่ ในพื้นที่สาธิต 4 เขต ได้แก่ **เขตบางซื่อ เขตจตุจักร เขตบางกะปิ และเขตลาดกระบัง** หน้าจอนี้แสดงถนนที่มีรายงานน้ำท่วม พร้อมเวลาและแหล่งที่มาของหลักฐานแต่ละชิ้น

เราต้องการแสดง **ตำแหน่งกล้อง CCTV ของ กทม. ใกล้ถนนที่มีรายงานน้ำท่วม** และให้เจ้าหน้าที่กด **เปิดหน้าดูกล้องทางการของ กทม.** ได้โดยตรง

- GRP จะ **ไม่บันทึกภาพ** และไม่ประมวลผลภาพใด ๆ
- ในการสาธิตบนเครื่องของทีมเท่านั้น GRP ส่งต่อภาพจาก www.bmatraffic.com ประมาณวินาทีละภาพ เฉพาะขณะที่เจ้าหน้าที่เปิดดู และไม่บันทึก เราขออนุญาตก่อนใช้ในวงกว้าง และขอทราบวิธีที่ กทม. ต้องการ เช่น ที่อยู่ภาพนิ่งที่ไม่ต้องใช้ session หรือที่อยู่แบบ HTTPS
- หากในอนาคตจะใช้ภาพนิ่งหรือการวิเคราะห์ภาพ เราจะขออนุญาตแยกต่างหาก
- **ปรับปรุง 4 ตุลาคม 2569:** ขณะนี้การสาธิตครอบคลุมกรุงเทพฯ ทั้ง 50 เขตแล้ว จึงขอข้อมูลกล้องทั้งกรุงเทพฯ
- **ขออนุญาตเพิ่มเติม (4 ตุลาคม 2569):** เราต้องการตรวจภาพจากกล้องใกล้จุดที่มีรายงานน้ำท่วมแบบอัตโนมัติ ให้ผลเพียงคำเดียว คือ **มีน้ำ** **มีน้ำบางส่วน** หรือ **แห้ง** โดยใช้ไม่เกิน 2 กล้องต่อเหตุการณ์ ทุก 15 นาที และไม่บันทึกภาพ ผลนี้ไม่แทนการตรวจของเจ้าหน้าที่ กทม. อนุญาตให้ทำเช่นนี้หรือไม่ และอนุญาตให้เผยแพร่ผลคำเดียวนี้ (โดยไม่มีภาพ ลิงก์ หรือรหัสกล้อง) ในฟีดข้อมูลน้ำท่วมสาธารณะหรือไม่

ขอความอนุเคราะห์ข้อมูลกล้องในสี่เขตนี้ (หรือทั้งกรุงเทพฯ หากสะดวกกว่า) ตามรายการด้านล่าง และขอทราบเงื่อนไขการใช้และการแสดงที่มาของข้อมูล

## English version

The ADPC SERVIR Global Risk Platform (GRP) pilot is testing an operator view for a demonstration
area of four districts: **Bang Sue, Chatuchak, Bang Kapi and Lat Krabang**. The view shows which roads have flooding
reported, with the time and source of each piece of evidence.

We would like to show **where BMA CCTV cameras are near reported flooding**, and let an officer
**open BMA's official camera viewer** from there.

- GRP will **not store or analyse any image or video**.
- In the team's local demo only, GRP passes on pictures from www.bmatraffic.com, about one a
  second, only while an officer is watching, and never stores them. We ask permission before any
  wider use, and how BMA would prefer it done: for example, a snapshot address that needs no
  session, or an HTTPS address.
- Any later use of snapshots or image analysis would be a separate, explicit request.

We ask for the following information for cameras in these four districts, or for all of Bangkok
if that is simpler. We would also like the terms of use and the attribution BMA requires.

## Information requested per camera

| Field | Why GRP needs it | Required? |
|---|---|---|
| Camera ID (as BMA uses it, for example `CM2-YW-32-C1`) | Stable identity and matching to BMA systems | Yes |
| Camera name or location description (Thai, English if available) | Shown to officers | Yes |
| Latitude and longitude | Map position, and finding cameras near a road | Yes |
| Link to the camera in BMA's official viewer, or the viewer page to use | The "open official viewer" button | Yes |
| Related flood sensor IDs (for example `FL.YNW.02`) | Linking a camera to a sensor | If available |
| Direction the camera faces, and field of view | So a camera facing away is never treated as seeing the road | If available |
| Current status (working, offline), and how GRP may check it | Offline cameras are shown as offline, never as "no flooding" | If available |
| Whether embedding the viewer in GRP is allowed | Otherwise GRP only opens BMA's page | Yes, yes or no |
| Terms of use, attribution and how long GRP may keep the list | Recorded in GRP's source registry | Yes |

## What GRP already does with the answer

- Each camera becomes one entry in GRP's camera registry (ADR-0039). Its access mode is
  "external viewer" or "embed", depending on BMA's permission.
- A camera is only a viewer link and a hint. It never confirms or rules out flooding by itself.
  An officer's own check is recorded separately.
- The three test entries now on the page are labelled as made up and will be removed.

## Contact

[Name, role, email of the person sending]
