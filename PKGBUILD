# Maintainer: UnDadFeated <jscheema@gmail.com>
pkgname=chronoarchiver
pkgver=1.0.15
pkgrel=1
pkgdesc="Unified Media Archive Organizer and AV1 Encoder - Time to Archive!"
arch=('any')
url="https://github.com/UnDadFeated/ChronoArchiver"
license=('MIT')
depends=(
    'python'
    'python-customtkinter'
    'python-opencv'
    'python-pillow'
    'python-piexif'
    'python-psutil'
    'python-platformdirs'
    'python-requests'
    'ffmpeg'
)
makedepends=('git' 'python-setuptools')
source=("git+https://github.com/UnDadFeated/ChronoArchiver.git#tag=v${pkgver}")
sha256sums=('SKIP')

package() {
    cd "${srcdir}/ChronoArchiver"
    
    # Create necessary directories
    install -d "${pkgdir}/usr/share/${pkgname}"
    install -d "${pkgdir}/usr/bin"
    install -d "${pkgdir}/usr/share/applications"
    install -d "${pkgdir}/usr/share/pixmaps"

    # Install main application files
    cp -rv src/* "${pkgdir}/usr/share/${pkgname}/"
    
    # Install the launcher script
    echo -e "#!/bin/bash\nexport PYTHONPATH=\$PYTHONPATH:/usr/share/${pkgname}\npython /usr/share/${pkgname}/ui/app.py \"\$@\"" > "${pkgdir}/usr/bin/${pkgname}"
    chmod +x "${pkgdir}/usr/bin/${pkgname}"

    # Install desktop entry
    install -m644 "chronoarchiver.desktop" "${pkgdir}/usr/share/applications/chronoarchiver.desktop"
    
    # Install application icon
    install -m644 "src/assets/icon.png" "${pkgdir}/usr/share/pixmaps/chronoarchiver.png"
}
