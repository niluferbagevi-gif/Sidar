import React, { useState, useEffect, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Sphere, MeshDistortMaterial } from '@react-three/drei';
import gsap from 'gsap';
import './App.css';

// 3D Parlayan Merkezi Çekirdek
const CoreMesh = () => {
  const meshRef = useRef();

  useFrame((state, delta) => {
    meshRef.current.rotation.x += delta * 0.2;
    meshRef.current.rotation.y += delta * 0.3;
  });

  return (
    <mesh ref={meshRef} scale={1.8}>
      <icosahedronGeometry args={[1, 1]} />
      <meshBasicMaterial color="#00ffff" wireframe />
      <Sphere args={[0.9, 32, 32]}>
        <MeshDistortMaterial color="#1a0033" attach="material" distort={0.4} speed={2} roughness={0} />
      </Sphere>
    </mesh>
  );
};

export default function App() {
  const [mode, setMode] = useState('web');
  const [provider, setProvider] = useState('ollama');
  const [level, setLevel] = useState('full');

  const panelRef = useRef(null);
  const titleRef = useRef(null);

  useEffect(() => {
    // PyWebView'den varsayılan ayarları çek
    const checkApi = setInterval(() => {
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.get_defaults().then((defaults) => {
          setProvider(defaults.provider);
          setLevel(defaults.level);
        });
        clearInterval(checkApi);
      }
    }, 100);

    // GSAP Giriş Animasyonları
    gsap.fromTo(titleRef.current, { y: -50, opacity: 0 }, { y: 0, opacity: 1, duration: 1, ease: 'power3.out' });
    gsap.fromTo(panelRef.current, { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 1, delay: 0.3, ease: 'back.out(1.7)' });

    return () => clearInterval(checkApi);
  }, []);

  const handleLaunch = () => {
    // Butona basıldığında ufak bir efekt
    gsap.to(panelRef.current, { scale: 0.95, opacity: 0, duration: 0.5, ease: 'power2.in' });

    setTimeout(() => {
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.launch_system(mode, provider, level);
      } else {
        console.log('Tarayıcı Modu: PyWebView bulunamadı.', { mode, provider, level });
      }
    }, 500);
  };

  const handleClose = () => {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.close_app();
  };

  return (
    <div className="app-container">
      {/* 3D Arka Plan Kanvası */}
      <div className="canvas-container">
        <Canvas>
          <ambientLight intensity={0.5} />
          <directionalLight position={[2, 2, 2]} intensity={1} />
          <CoreMesh />
          <OrbitControls enableZoom={false} autoRotate autoRotateSpeed={0.5} />
        </Canvas>
      </div>

      {/* Kapatma Butonu (Frameless olduğu için gerekli) */}
      <button className="close-btn" onClick={handleClose}>✖</button>

      {/* Ön Katman UI Paneli */}
      <div className="ui-layer">
        <h1 ref={titleRef} className="cyber-title">SİDAR AI <span>CORE</span></h1>

        <div ref={panelRef} className="glass-panel">
          <div className="control-group">
            <label>1. ARAYÜZ MODU</label>
            <div className="btn-group">
              <button className={mode === 'web' ? 'active' : ''} onClick={() => setMode('web')}>WEB UI</button>
              <button className={mode === 'cli' ? 'active' : ''} onClick={() => setMode('cli')}>TERMINAL</button>
            </div>
          </div>

          <div className="control-group">
            <label>2. AI SAĞLAYICI</label>
            <div className="btn-group">
              <button className={provider === 'ollama' ? 'active' : ''} onClick={() => setProvider('ollama')}>OLLAMA</button>
              <button className={provider === 'gemini' ? 'active' : ''} onClick={() => setProvider('gemini')}>GEMINI</button>
            </div>
          </div>

          <div className="control-group">
            <label>3. YETKİ SEVİYESİ</label>
            <select value={level} onChange={(e) => setLevel(e.target.value)} className="cyber-select">
              <option value="full">FULL (Sınırsız Erişim)</option>
              <option value="sandbox">SANDBOX (İzole)</option>
              <option value="restricted">RESTRICTED (Sadece Okuma)</option>
            </select>
          </div>

          <button className="launch-btn" onClick={handleLaunch}>SİSTEMİ BAŞLAT</button>
        </div>
      </div>
    </div>
  );
}
