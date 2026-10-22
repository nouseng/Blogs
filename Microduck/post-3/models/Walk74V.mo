model Walk74V
  extends Duck.Examples.WalkingTest(forwardSpeed = 0.3, checkResults = false, robot(supplyVoltage = 7.4));
  Real motorCurrent[14] = {(robot.leftHipYaw.servo.voltage - robot.leftHipYaw.servo.torqueConstant * robot.leftHipYaw.servo.speedSensor.w_rel) / robot.leftHipYaw.servo.resistance,
    (robot.leftHipRoll.servo.voltage - robot.leftHipRoll.servo.torqueConstant * robot.leftHipRoll.servo.speedSensor.w_rel) / robot.leftHipRoll.servo.resistance,
    (robot.leftHipPitch.servo.voltage - robot.leftHipPitch.servo.torqueConstant * robot.leftHipPitch.servo.speedSensor.w_rel) / robot.leftHipPitch.servo.resistance,
    (robot.leftKnee.servo.voltage - robot.leftKnee.servo.torqueConstant * robot.leftKnee.servo.speedSensor.w_rel) / robot.leftKnee.servo.resistance,
    (robot.leftAnkle.servo.voltage - robot.leftAnkle.servo.torqueConstant * robot.leftAnkle.servo.speedSensor.w_rel) / robot.leftAnkle.servo.resistance,
    (robot.neckPitch.servo.voltage - robot.neckPitch.servo.torqueConstant * robot.neckPitch.servo.speedSensor.w_rel) / robot.neckPitch.servo.resistance,
    (robot.headPitch.servo.voltage - robot.headPitch.servo.torqueConstant * robot.headPitch.servo.speedSensor.w_rel) / robot.headPitch.servo.resistance,
    (robot.headYaw.servo.voltage - robot.headYaw.servo.torqueConstant * robot.headYaw.servo.speedSensor.w_rel) / robot.headYaw.servo.resistance,
    (robot.headRoll.servo.voltage - robot.headRoll.servo.torqueConstant * robot.headRoll.servo.speedSensor.w_rel) / robot.headRoll.servo.resistance,
    (robot.rightHipYaw.servo.voltage - robot.rightHipYaw.servo.torqueConstant * robot.rightHipYaw.servo.speedSensor.w_rel) / robot.rightHipYaw.servo.resistance,
    (robot.rightHipRoll.servo.voltage - robot.rightHipRoll.servo.torqueConstant * robot.rightHipRoll.servo.speedSensor.w_rel) / robot.rightHipRoll.servo.resistance,
    (robot.rightHipPitch.servo.voltage - robot.rightHipPitch.servo.torqueConstant * robot.rightHipPitch.servo.speedSensor.w_rel) / robot.rightHipPitch.servo.resistance,
    (robot.rightKnee.servo.voltage - robot.rightKnee.servo.torqueConstant * robot.rightKnee.servo.speedSensor.w_rel) / robot.rightKnee.servo.resistance,
    (robot.rightAnkle.servo.voltage - robot.rightAnkle.servo.torqueConstant * robot.rightAnkle.servo.speedSensor.w_rel) / robot.rightAnkle.servo.resistance} "Motor current of each servo";
  Real batteryCurrent = robot.leftHipYaw.servo.drive * motorCurrent[1] +
    robot.leftHipRoll.servo.drive * motorCurrent[2] +
    robot.leftHipPitch.servo.drive * motorCurrent[3] +
    robot.leftKnee.servo.drive * motorCurrent[4] +
    robot.leftAnkle.servo.drive * motorCurrent[5] +
    robot.neckPitch.servo.drive * motorCurrent[6] +
    robot.headPitch.servo.drive * motorCurrent[7] +
    robot.headYaw.servo.drive * motorCurrent[8] +
    robot.headRoll.servo.drive * motorCurrent[9] +
    robot.rightHipYaw.servo.drive * motorCurrent[10] +
    robot.rightHipRoll.servo.drive * motorCurrent[11] +
    robot.rightHipPitch.servo.drive * motorCurrent[12] +
    robot.rightKnee.servo.drive * motorCurrent[13] +
    robot.rightAnkle.servo.drive * motorCurrent[14] "Current drawn by all servos from an ideal supply";
end Walk74V;
