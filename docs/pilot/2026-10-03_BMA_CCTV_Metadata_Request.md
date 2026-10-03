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

## Thai version (ฉบับภาษาไทย)

เรียน สำนักการระบายน้ำ กรุงเทพมหานคร

ทีมนำร่อง SERVIR Global Risk Platform (GRP) ของ ADPC กำลังทดลองหน้าจอสำหรับเจ้าหน้าที่ ในพื้นที่สาธิต 4 เขต ได้แก่ **เขตบางซื่อ เขตจตุจักร เขตบางกะปิ และเขตลาดกระบัง** หน้าจอนี้แสดงถนนที่มีรายงานน้ำท่วม พร้อมเวลาและแหล่งที่มาของหลักฐานแต่ละชิ้น

เราต้องการแสดง **ตำแหน่งกล้อง CCTV ของ กทม. ใกล้ถนนที่มีรายงานน้ำท่วม** และให้เจ้าหน้าที่กด **เปิดหน้าดูกล้องทางการของ กทม.** ได้โดยตรง

- GRP จะ **ไม่ดึงภาพหรือวิดีโอ** ไม่บันทึกภาพ และไม่ประมวลผลภาพใด ๆ
- หากในอนาคตจะใช้ภาพนิ่งหรือการวิเคราะห์ภาพ เราจะขออนุญาตแยกต่างหาก

ขอความอนุเคราะห์ข้อมูลกล้องในสี่เขตนี้ (หรือทั้งกรุงเทพฯ หากสะดวกกว่า) ตามรายการด้านล่าง และขอทราบเงื่อนไขการใช้และการแสดงที่มาของข้อมูล

## English version

The ADPC SERVIR Global Risk Platform (GRP) pilot is testing an operator view for a demonstration
area of four districts: **Bang Sue, Chatuchak, Bang Kapi and Lat Krabang**. The view shows which roads have flooding
reported, with the time and source of each piece of evidence.

We would like to show **where BMA CCTV cameras are near reported flooding**, and let an officer
**open BMA's official camera viewer** from there.

- GRP will **not fetch, store or analyse any image or video**.
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
