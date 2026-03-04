import React from 'react'
import { createRoot } from 'react-dom/client'
import { gsap } from 'gsap'
import * as THREE from 'three'
import './styles.css'

function App() {
  React.useEffect(() => {
    gsap.from('.wizard', { opacity: 0, y: 18, duration: 0.5 })

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000)
    const renderer = new THREE.WebGLRenderer({ alpha: true })
    renderer.setSize(220, 220)
    document.getElementById('three-bg')?.appendChild(renderer.domElement)

    const geometry = new THREE.TorusGeometry(1.2, 0.3, 12, 40)
    const material = new THREE.MeshBasicMaterial({ color: 0x3f7bff, wireframe: true })
    const torus = new THREE.Mesh(geometry, material)
    scene.add(torus)
    camera.position.z = 3

    const animate = () => {
      torus.rotation.x += 0.01
      torus.rotation.y += 0.008
      renderer.render(scene, camera)
      requestAnimationFrame(animate)
    }
    animate()

    return () => renderer.dispose()
  }, [])

  return (
    <div className="page">
      <div id="three-bg" />
      <div className="wizard">
        <h1>Sidar Launcher (React/Vite)</h1>
        <p>Bu proje pywebview içinde `window.pywebview.api` kullanacak şekilde genişletilmeye hazırdır.</p>
      </div>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)