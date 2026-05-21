Add-Type -AssemblyName System.Drawing
$img1Path = "images/photo_2026-05-21_12-05-37.jpg"
$img1 = [System.Drawing.Image]::FromFile($img1Path)
$img1.RotateFlip([System.Drawing.RotateFlipType]::Rotate270FlipNone)
$img1.Save("images/photo_2026-05-21_12-05-37_r.jpg", [System.Drawing.Imaging.ImageFormat]::Jpeg)
$img1.Dispose()
Remove-Item $img1Path
Rename-Item "images/photo_2026-05-21_12-05-37_r.jpg" "photo_2026-05-21_12-05-37.jpg"

$img2Path = "images/photo_2026-05-21_12-05-35.jpg"
$img2 = [System.Drawing.Image]::FromFile($img2Path)
$img2.RotateFlip([System.Drawing.RotateFlipType]::Rotate90FlipNone)
$img2.Save("images/photo_2026-05-21_12-05-35_r.jpg", [System.Drawing.Imaging.ImageFormat]::Jpeg)
$img2.Dispose()
Remove-Item $img2Path
Rename-Item "images/photo_2026-05-21_12-05-35_r.jpg" "photo_2026-05-21_12-05-35.jpg"
