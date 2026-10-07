# Request to Nakhon Nonthaburi City Municipality: a camera data feed

**Date:** 4 October 2026
**From:** the SERVIR Global Risk Platform (GRP) pilot team, ADPC
**Status:** draft for the Product Owner to send. Nothing has been sent.

## Thai version (ฉบับภาษาไทย)

เรียน เทศบาลนครนนทบุรี

ทีมนำร่อง SERVIR Global Risk Platform (GRP) ของ ADPC กำลังทดลองระบบสนับสนุนการวางแผนรับมือน้ำท่วม
สำหรับกรุงเทพฯ และนนทบุรี ระบบแสดงถนนที่มีรายงานน้ำท่วม สถานที่สำคัญใกล้เคียง รวมถึงศูนย์พักพิงของ ปภ.
และกล้องใกล้จุดนั้น

ระบบสารสนเทศของเทศบาล (https://nkndatamap.nakornnont.go.th/public) มีข้อมูลกล้อง CCTV ในเขตเทศบาล
ซึ่งจะช่วยให้เจ้าหน้าที่เห็นสถานการณ์ในอำเภอเมืองนนทบุรีได้ดีขึ้น ขณะนี้ GRP ยังไม่มีกล้องในพื้นที่นี้

เราไม่ต้องการดึงข้อมูลจากหน้าเว็บโดยไม่ได้รับอนุญาต จึงขอความอนุเคราะห์:

1. **รายการกล้อง** (รหัส ชื่อ พิกัด และสถานะ) ในรูปแบบไฟล์หรือ API ที่เผยแพร่ได้
2. **วิธีดูภาพจากกล้อง** ที่เทศบาลยินดีให้ใช้ (ลิงก์ภาพนิ่ง หรือลิงก์หน้าดูภาพของเทศบาล)
3. **เงื่อนไขการใช้งานและการระบุแหล่งที่มา**

GRP จะไม่บันทึกภาพ จะดึงภาพเฉพาะเมื่อเจ้าหน้าที่เปิดดู และจะระบุแหล่งที่มาเป็นเทศบาลนครนนทบุรีทุกครั้ง

ขอแสดงความนับถือ
[ชื่อผู้รับผิดชอบ] ทีม GRP, ADPC

## English summary

- The municipality's GIS site has CCTV data, but no public interface. GRP will not extract it
  from the page.
- We ask for a camera list (ID, name, position, status), a permitted way to view pictures, and
  terms and credit.
- GRP would store no pictures, fetch only while an officer looks, and always credit the
  municipality.
- Mueang Nonthaburi currently has no camera in GRP.
